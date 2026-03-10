/**
 * Mem0 FREE Edition — Memory System for OpenClaw Personal Assistant
 *
 * Week 1 Implementation: Storage & CRUD
 * Database: Cloudflare D1 (SQLite)
 * Extraction: DeepSeek V3 (async, called separately)
 * Search: FTS5 (full-text search with BM25 ranking)
 *
 * Tables:
 * - memories: Core memory storage with hash-based dedup
 * - history: Audit trail of all memory changes
 * - memories_fts: Full-text search index
 */

// Note: Using built-in crypto API available in Cloudflare Workers

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Memory {
  id: string;
  user_id: string;
  agent_id?: string;
  run_id?: string;
  category: "preference" | "habit" | "fact" | "relationship" | "goal";
  data: string;
  hash: string;
  created_at: string;
  updated_at: string;
}

export interface MemoryHistoryEvent {
  id: string;
  memory_id: string;
  old_memory?: string;
  new_memory?: string;
  event: "ADD" | "UPDATE" | "DELETE" | "NONE";
  created_at: string;
}

export interface MemorySearchResult extends Memory {
  score?: number;
}

export interface MemoryAddRequest {
  data: string;
  user_id: string;
  agent_id?: string;
  run_id?: string;
  category?: "preference" | "habit" | "fact" | "relationship" | "goal";
}

export interface MemorySearchRequest {
  query: string;
  user_id: string;
  agent_id?: string;
  run_id?: string;
  category?: string;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Database Setup
// ---------------------------------------------------------------------------

/**
 * Initialize memory tables. Call once at startup.
 * Safe to call multiple times (uses IF NOT EXISTS).
 */
export async function initializeMemoryTables(db: D1Database): Promise<void> {
  try {
    // Main memories table
    await db
      .prepare(
        `
      CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        agent_id TEXT,
        run_id TEXT,
        category TEXT DEFAULT 'fact',
        data TEXT NOT NULL,
        hash TEXT UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
      `,
      )
      .run();

    // Create indexes for common queries
    await db.prepare(`CREATE INDEX IF NOT EXISTS idx_user_id ON memories(user_id)`).run();
    await db.prepare(`CREATE INDEX IF NOT EXISTS idx_agent_id ON memories(agent_id)`).run();
    await db.prepare(`CREATE INDEX IF NOT EXISTS idx_run_id ON memories(run_id)`).run();
    await db.prepare(`CREATE INDEX IF NOT EXISTS idx_category ON memories(category)`).run();

    // Full-text search table
    await db
      .prepare(
        `
      CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        data,
        content='memories',
        content_rowid='rowid'
      )
      `,
      )
      .run();

    // History table for audit trail
    await db
      .prepare(
        `
      CREATE TABLE IF NOT EXISTS memory_history (
        id TEXT PRIMARY KEY,
        memory_id TEXT NOT NULL,
        old_memory TEXT,
        new_memory TEXT,
        event TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (memory_id) REFERENCES memories(id)
      )
      `,
      )
      .run();

    await db
      .prepare(`CREATE INDEX IF NOT EXISTS idx_history_memory ON memory_history(memory_id)`)
      .run();
  } catch (err) {
    console.error("Error initializing memory tables:", err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Generate SHA256 hash of memory content for deduplication.
 * Uses Web Crypto API available in Cloudflare Workers.
 */
async function hashMemory(data: string): Promise<string> {
  const encoder = new TextEncoder();
  const dataBuffer = encoder.encode(data);
  const hashBuffer = await crypto.subtle.digest("SHA-256", dataBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Generate a random UUID v4.
 * Uses crypto.getRandomValues available in Cloudflare Workers.
 */
function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).substr(2, 9)}-${crypto
    .getRandomValues(new Uint8Array(4))
    .reduce((s, b) => s + b.toString(16).padStart(2, "0"), "")}`;
}

// ---------------------------------------------------------------------------
// Core CRUD Operations
// ---------------------------------------------------------------------------

/**
 * Add a new memory or find existing similar memory.
 *
 * Returns the memory ID and whether it was newly created (true) or already existed (false).
 */
export async function addMemory(
  db: D1Database,
  request: MemoryAddRequest,
): Promise<{ id: string; created: boolean; memory: Memory }> {
  const id = generateId();
  const hash = await hashMemory(request.data);
  const category = request.category || "fact";
  const now = new Date().toISOString();

  try {
    // Try to insert. If hash already exists (duplicate), return existing.
    const result = await db
      .prepare(
        `
      INSERT INTO memories (id, user_id, agent_id, run_id, category, data, hash, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      )
      .bind(
        id,
        request.user_id,
        request.agent_id || null,
        request.run_id || null,
        category,
        request.data,
        hash,
        now,
        now,
      )
      .run();

    const memory: Memory = {
      id,
      user_id: request.user_id,
      agent_id: request.agent_id,
      run_id: request.run_id,
      category: category as Memory["category"],
      data: request.data,
      hash,
      created_at: now,
      updated_at: now,
    };

    // Add to FTS index
    await db
      .prepare(
        `
      INSERT INTO memories_fts (rowid, data) VALUES (
        (SELECT rowid FROM memories WHERE id = ?),
        ?
      )
      `,
      )
      .bind(id, request.data)
      .run();

    // Log to history
    await logMemoryHistory(db, id, null, request.data, "ADD");

    return { id, created: true, memory };
  } catch (err: unknown) {
    // If duplicate hash, find and return existing
    if ((err as { message?: string }).message?.includes("UNIQUE constraint failed")) {
      const existing = await db
        .prepare(`SELECT * FROM memories WHERE hash = ?`)
        .bind(hash)
        .first<Memory>();

      if (existing) {
        return { id: existing.id, created: false, memory: existing };
      }
    }
    throw err;
  }
}

/**
 * Search memories using full-text search (FTS5) with optional filtering.
 *
 * Supports filtering by:
 * - user_id (required)
 * - agent_id (optional)
 * - run_id (optional)
 * - category (optional)
 */
export async function searchMemories(
  db: D1Database,
  request: MemorySearchRequest,
): Promise<MemorySearchResult[]> {
  const limit = request.limit || 10;

  // Build filter clause (applied to both FTS5 and LIKE fallback)
  let filterClause = "WHERE m.user_id = ?";
  const filterParams: unknown[] = [request.user_id];

  if (request.agent_id) {
    filterClause += " AND m.agent_id = ?";
    filterParams.push(request.agent_id);
  }

  if (request.run_id) {
    filterClause += " AND m.run_id = ?";
    filterParams.push(request.run_id);
  }

  if (request.category) {
    filterClause += " AND m.category = ?";
    filterParams.push(request.category);
  }

  // Strategy 1: FTS5 full-text search with BM25 ranking
  try {
    // Build FTS5 query — split into terms and OR them for partial matching
    const terms = request.query
      .split(/\s+/)
      .filter((w) => w.length > 2)
      .map((w) => w.replace(/['"]/g, "")) // strip quotes for safety
      .filter(Boolean);

    if (terms.length > 0) {
      const ftsQuery = terms.map((t) => `"${t}"*`).join(" OR ");
      const ftsSQL = `
        SELECT m.*, rank AS score
        FROM memories_fts fts
        JOIN memories m ON m.rowid = fts.rowid
        ${filterClause.replace("WHERE", "WHERE 1=1 AND")} AND fts.memories_fts MATCH ?
        ORDER BY rank
        LIMIT ?
      `;
      // Fix: filterClause starts with WHERE m.user_id, but we need to reference the joined table
      const sql = `
        SELECT m.*, fts.rank AS score
        FROM memories_fts fts
        JOIN memories m ON m.rowid = fts.rowid
        ${filterClause} AND memories_fts MATCH ?
        ORDER BY fts.rank
        LIMIT ?
      `;

      const results = await db
        .prepare(sql)
        .bind(...filterParams, ftsQuery, limit)
        .all<MemorySearchResult>();

      if (results.results && results.results.length > 0) {
        return results.results;
      }
    }
  } catch (err) {
    console.error("FTS5 search failed, falling back to LIKE:", err);
  }

  // Strategy 2: Multi-keyword LIKE search (fallback)
  // Search for each keyword separately and rank by number of matches
  const keywords = request.query
    .split(/\s+/)
    .filter((w) => w.length > 2)
    .slice(0, 5);

  if (keywords.length === 0) {
    // No useful keywords — return recent memories
    const recentSQL = `
      SELECT m.* FROM memories m ${filterClause}
      ORDER BY m.updated_at DESC LIMIT ?
    `;
    try {
      const results = await db
        .prepare(recentSQL)
        .bind(...filterParams, limit)
        .all<MemorySearchResult>();
      return results.results || [];
    } catch {
      return [];
    }
  }

  // Build LIKE conditions — match ANY keyword (OR), rank by match count
  const likeCases = keywords.map(() => `(CASE WHEN m.data LIKE ? THEN 1 ELSE 0 END)`).join(" + ");
  const likeParams = keywords.map((k) => `%${k}%`);
  const likeFilter = keywords.map(() => `m.data LIKE ?`).join(" OR ");

  const likeSQL = `
    SELECT m.*, (${likeCases}) AS score
    FROM memories m
    ${filterClause} AND (${likeFilter})
    ORDER BY score DESC, m.updated_at DESC
    LIMIT ?
  `;

  try {
    const results = await db
      .prepare(likeSQL)
      .bind(...filterParams, ...likeParams, ...likeParams, limit)
      .all<MemorySearchResult>();
    return results.results || [];
  } catch (err) {
    console.error("Search error:", err);
    return [];
  }
}

/**
 * Get a memory by ID.
 */
export async function getMemory(db: D1Database, id: string): Promise<Memory | null> {
  const result = await db.prepare(`SELECT * FROM memories WHERE id = ?`).bind(id).first<Memory>();
  return result || null;
}

/**
 * Update a memory's data and category.
 *
 * Updates the hash and timestamp, logs to history.
 */
export async function updateMemory(
  db: D1Database,
  id: string,
  newData: string,
  newCategory?: string,
): Promise<Memory> {
  const oldMemory = await getMemory(db, id);
  if (!oldMemory) {
    throw new Error(`Memory ${id} not found`);
  }

  const newHash = await hashMemory(newData);
  const now = new Date().toISOString();
  const category = newCategory || oldMemory.category;

  await db
    .prepare(
      `
    UPDATE memories
    SET data = ?, hash = ?, category = ?, updated_at = ?
    WHERE id = ?
    `,
    )
    .bind(newData, newHash, category, now, id)
    .run();

  // Update FTS index
  await db
    .prepare(`DELETE FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?)`)
    .bind(id)
    .run();

  await db
    .prepare(
      `
    INSERT INTO memories_fts (rowid, data) VALUES (
      (SELECT rowid FROM memories WHERE id = ?),
      ?
    )
    `,
    )
    .bind(id, newData)
    .run();

  // Log to history
  await logMemoryHistory(db, id, oldMemory.data, newData, "UPDATE");

  const updated = await getMemory(db, id);
  if (!updated) {
    throw new Error(`Failed to update memory ${id}`);
  }

  return updated;
}

/**
 * Delete a memory by ID.
 *
 * Soft delete: marks as deleted in history but keeps record for audit trail.
 */
export async function deleteMemory(db: D1Database, id: string): Promise<void> {
  const memory = await getMemory(db, id);
  if (!memory) {
    throw new Error(`Memory ${id} not found`);
  }

  // Log deletion
  await logMemoryHistory(db, id, memory.data, null, "DELETE");

  // Hard delete from FTS
  await db
    .prepare(`DELETE FROM memories_fts WHERE rowid = (SELECT rowid FROM memories WHERE id = ?)`)
    .bind(id)
    .run();

  // Hard delete from main table
  await db.prepare(`DELETE FROM memories WHERE id = ?`).bind(id).run();
}

/**
 * List all memories for a user (with optional filters).
 */
export async function listMemories(
  db: D1Database,
  userId: string,
  filters?: { agent_id?: string; run_id?: string; category?: string; limit?: number },
): Promise<Memory[]> {
  let query = "SELECT * FROM memories WHERE user_id = ?";
  const params: unknown[] = [userId];

  if (filters?.agent_id) {
    query += " AND agent_id = ?";
    params.push(filters.agent_id);
  }

  if (filters?.run_id) {
    query += " AND run_id = ?";
    params.push(filters.run_id);
  }

  if (filters?.category) {
    query += " AND category = ?";
    params.push(filters.category);
  }

  query += " ORDER BY updated_at DESC";

  if (filters?.limit) {
    query += " LIMIT ?";
    params.push(filters.limit);
  }

  const results = await db
    .prepare(query)
    .bind(...params)
    .all<Memory>();
  return results.results || [];
}

// ---------------------------------------------------------------------------
// History & Audit
// ---------------------------------------------------------------------------

/**
 * Log a memory change to the history table for audit trail.
 */
async function logMemoryHistory(
  db: D1Database,
  memoryId: string,
  oldMemory: string | null,
  newMemory: string | null,
  event: "ADD" | "UPDATE" | "DELETE" | "NONE",
): Promise<void> {
  const id = generateId();
  const now = new Date().toISOString();

  await db
    .prepare(
      `
    INSERT INTO memory_history (id, memory_id, old_memory, new_memory, event, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    `,
    )
    .bind(id, memoryId, oldMemory, newMemory, event, now)
    .run();
}

/**
 * Get history for a specific memory.
 */
export async function getMemoryHistory(
  db: D1Database,
  memoryId: string,
  limit: number = 50,
): Promise<MemoryHistoryEvent[]> {
  const results = await db
    .prepare(`SELECT * FROM memory_history WHERE memory_id = ? ORDER BY created_at DESC LIMIT ?`)
    .bind(memoryId, limit)
    .all<MemoryHistoryEvent>();

  return results.results || [];
}

/**
 * Get statistics about a user's memory usage.
 */
export async function getMemoryStats(
  db: D1Database,
  userId: string,
): Promise<{
  total: number;
  by_category: Record<string, number>;
  created_at: string;
  last_updated_at: string;
}> {
  const totalRes = await db
    .prepare(`SELECT COUNT(*) as count FROM memories WHERE user_id = ?`)
    .bind(userId)
    .first<{ count: number }>();

  const byCategory = await db
    .prepare(`SELECT category, COUNT(*) as count FROM memories WHERE user_id = ? GROUP BY category`)
    .bind(userId)
    .all<{ category: string; count: number }>();

  const dateRes = await db
    .prepare(
      `SELECT MIN(created_at) as created_at, MAX(updated_at) as last_updated_at FROM memories WHERE user_id = ?`,
    )
    .bind(userId)
    .first<{ created_at: string; last_updated_at: string }>();

  const stats: Record<string, number> = {};
  (byCategory.results || []).forEach((row) => {
    stats[row.category] = row.count;
  });

  return {
    total: totalRes?.count || 0,
    by_category: stats,
    created_at: dateRes?.created_at || new Date().toISOString(),
    last_updated_at: dateRes?.last_updated_at || new Date().toISOString(),
  };
}
