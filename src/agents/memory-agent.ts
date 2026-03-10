/**
 * Memory Agent — persistent knowledge management across sessions.
 *
 * Uses node:sqlite (via the project helper) for local persistence and a
 * Redis-compatible client for distributed session caching with a 1-hour TTL.
 *
 * Tables auto-created on init:
 *   users        — user profiles and preferences
 *   sessions     — chat sessions tied to users and channels
 *   messages     — individual messages within sessions
 *   context      — arbitrary key/value context per session
 */

import type { DatabaseSync, StatementSync } from "node:sqlite";
import path from "node:path";
import { requireNodeSqlite } from "../memory/sqlite.js";

// ---------------------------------------------------------------------------
// Redis client interface (mirrors the pattern in agency-cost-tracker.ts)
// ---------------------------------------------------------------------------

export interface MemoryRedisClient {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { ex?: number }): Promise<string>;
  del(...keys: string[]): Promise<number>;
  expire(key: string, seconds: number): Promise<number>;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UserProfile {
  id: string;
  display_name: string;
  channel: string;
  preferences: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  user_id: string;
  session_key: string;
  channel: string;
  started_at: string;
  last_active_at: string;
  metadata: Record<string, unknown>;
}

export interface Message {
  id: number;
  session_key: string;
  role: string;
  content: string;
  tokens: number;
  cost: number;
  created_at: string;
}

export interface ContextEntry {
  session_key: string;
  key: string;
  value: string;
  updated_at: string;
}

export interface VisionMemory {
  id: string;
  device_id: string;
  session_key: string;
  query_type: string;
  image_hash: string;
  description: string;
  tags: string;
  created_at: string;
  cost_usd: number;
}

export interface MemoryAgentOptions {
  /** Directory where the SQLite database file is stored. */
  dataDir: string;
  /** Optional Redis client for distributed caching. */
  redis?: MemoryRedisClient;
  /** Cache TTL in seconds (default: 3600 — one hour). */
  cacheTtlSeconds?: number;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DB_FILENAME = "memory-agent.db";
const DEFAULT_CACHE_TTL = 3600; // 1 hour
const REDIS_PREFIX = "memory-agent:";

// ---------------------------------------------------------------------------
// MemoryAgent
// ---------------------------------------------------------------------------

export class MemoryAgent {
  private readonly db: DatabaseSync;
  private readonly redis: MemoryRedisClient | undefined;
  private readonly cacheTtl: number;

  // Prepared statements (lazily populated after table init).
  private stmts!: {
    insertUser: StatementSync;
    getUser: StatementSync;
    updateUserPrefs: StatementSync;
    insertSession: StatementSync;
    getSession: StatementSync;
    touchSession: StatementSync;
    insertMessage: StatementSync;
    recentMessages: StatementSync;
    getContext: StatementSync;
    upsertContext: StatementSync;
    insertVision: StatementSync;
    recentVision: StatementSync;
    searchVision: StatementSync;
    deleteVision: StatementSync;
  };

  constructor(options: MemoryAgentOptions) {
    const { DatabaseSync: DbSync } = requireNodeSqlite();
    const dbPath = path.join(options.dataDir, DB_FILENAME);
    this.db = new DbSync(dbPath);
    this.redis = options.redis;
    this.cacheTtl = options.cacheTtlSeconds ?? DEFAULT_CACHE_TTL;

    this.ensureTables();
    this.prepareStatements();
  }

  // -----------------------------------------------------------------------
  // Schema bootstrap
  // -----------------------------------------------------------------------

  private ensureTables(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        display_name  TEXT NOT NULL DEFAULT '',
        channel       TEXT NOT NULL DEFAULT '',
        preferences   TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS sessions (
        id             TEXT PRIMARY KEY,
        user_id        TEXT NOT NULL,
        session_key    TEXT NOT NULL UNIQUE,
        channel        TEXT NOT NULL DEFAULT '',
        started_at     TEXT NOT NULL DEFAULT (datetime('now')),
        last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
        metadata       TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (user_id) REFERENCES users(id)
      );

      CREATE INDEX IF NOT EXISTS idx_sessions_user   ON sessions(user_id);
      CREATE INDEX IF NOT EXISTS idx_sessions_key    ON sessions(session_key);

      CREATE TABLE IF NOT EXISTS messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_key TEXT NOT NULL,
        role        TEXT NOT NULL,
        content     TEXT NOT NULL DEFAULT '',
        tokens      INTEGER NOT NULL DEFAULT 0,
        cost        REAL NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (session_key) REFERENCES sessions(session_key)
      );

      CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key);

      CREATE TABLE IF NOT EXISTS context (
        session_key TEXT NOT NULL,
        key         TEXT NOT NULL,
        value       TEXT NOT NULL DEFAULT '',
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (session_key, key),
        FOREIGN KEY (session_key) REFERENCES sessions(session_key)
      );

      CREATE TABLE IF NOT EXISTS vision_memories (
        id          TEXT PRIMARY KEY,
        device_id   TEXT NOT NULL,
        session_key TEXT NOT NULL,
        query_type  TEXT NOT NULL,
        image_hash  TEXT NOT NULL,
        description TEXT NOT NULL,
        tags        TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        cost_usd    REAL DEFAULT 0.0
      );

      CREATE INDEX IF NOT EXISTS idx_vision_device ON vision_memories(device_id);
      CREATE INDEX IF NOT EXISTS idx_vision_tags   ON vision_memories(tags);
    `);
  }

  // -----------------------------------------------------------------------
  // Prepared statements
  // -----------------------------------------------------------------------

  private prepareStatements(): void {
    this.stmts = {
      insertUser: this.db.prepare(
        `INSERT OR IGNORE INTO users (id, display_name, channel, preferences)
         VALUES (?, ?, ?, ?)`,
      ),
      getUser: this.db.prepare(`SELECT * FROM users WHERE id = ?`),
      updateUserPrefs: this.db.prepare(
        `UPDATE users SET preferences = ?, updated_at = datetime('now') WHERE id = ?`,
      ),
      insertSession: this.db.prepare(
        `INSERT OR IGNORE INTO sessions (id, user_id, session_key, channel, metadata)
         VALUES (?, ?, ?, ?, ?)`,
      ),
      getSession: this.db.prepare(`SELECT * FROM sessions WHERE session_key = ?`),
      touchSession: this.db.prepare(
        `UPDATE sessions SET last_active_at = datetime('now') WHERE session_key = ?`,
      ),
      insertMessage: this.db.prepare(
        `INSERT INTO messages (session_key, role, content, tokens, cost)
         VALUES (?, ?, ?, ?, ?)`,
      ),
      recentMessages: this.db.prepare(
        `SELECT * FROM messages WHERE session_key = ? ORDER BY id DESC LIMIT ?`,
      ),
      getContext: this.db.prepare(`SELECT * FROM context WHERE session_key = ?`),
      upsertContext: this.db.prepare(
        `INSERT INTO context (session_key, key, value, updated_at)
         VALUES (?, ?, ?, datetime('now'))
         ON CONFLICT(session_key, key)
         DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
      ),
      insertVision: this.db.prepare(
        `INSERT INTO vision_memories (id, device_id, session_key, query_type, image_hash, description, tags, cost_usd)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      ),
      recentVision: this.db.prepare(
        `SELECT * FROM vision_memories WHERE device_id = ? ORDER BY created_at DESC LIMIT ?`,
      ),
      searchVision: this.db.prepare(
        `SELECT * FROM vision_memories
         WHERE (description LIKE ? OR tags LIKE ?)
           AND (? IS NULL OR device_id = ?)
         ORDER BY created_at DESC LIMIT ?`,
      ),
      deleteVision: this.db.prepare(`DELETE FROM vision_memories WHERE device_id = ?`),
    };
  }

  // -----------------------------------------------------------------------
  // Session management
  // -----------------------------------------------------------------------

  /**
   * Load a session — checks Redis cache first, then falls back to SQLite.
   */
  async loadSession(sessionKey: string): Promise<Session | null> {
    // Try Redis cache first.
    if (this.redis) {
      try {
        const cached = await this.redis.get(this.cacheKey("session", sessionKey));
        if (cached) {
          return JSON.parse(cached) as Session;
        }
      } catch {
        // Redis miss or error — fall through to SQLite.
      }
    }

    // Fall back to SQLite.
    const row = this.stmts.getSession.get(sessionKey) as Record<string, unknown> | undefined;
    if (!row) {
      return null;
    }
    const session = this.rowToSession(row);

    // Populate cache for next lookup.
    await this.cacheSet("session", sessionKey, session);
    return session;
  }

  /**
   * Create a new session for a user and channel.
   * If the user does not exist yet, a stub profile is created automatically.
   */
  async createSession(userId: string, channel: string): Promise<Session> {
    // Ensure user exists.
    this.stmts.insertUser.run(userId, "", channel, "{}");

    const sessionKey = `${channel}:${userId}:${Date.now()}`;
    const id = crypto.randomUUID();

    this.stmts.insertSession.run(id, userId, sessionKey, channel, "{}");

    const session: Session = {
      id,
      user_id: userId,
      session_key: sessionKey,
      channel,
      started_at: new Date().toISOString(),
      last_active_at: new Date().toISOString(),
      metadata: {},
    };

    await this.cacheSet("session", sessionKey, session);
    return session;
  }

  // -----------------------------------------------------------------------
  // Messages
  // -----------------------------------------------------------------------

  /**
   * Persist a single message and touch the session timestamp.
   */
  async saveMessage(
    sessionKey: string,
    role: string,
    content: string,
    tokens: number,
    cost: number,
  ): Promise<void> {
    this.stmts.insertMessage.run(sessionKey, role, content, tokens, cost);
    this.stmts.touchSession.run(sessionKey);

    // Invalidate the cached session so the next load picks up the new timestamp.
    await this.cacheInvalidate("session", sessionKey);
  }

  /**
   * Return the most recent messages for a session (newest first).
   */
  getRecentMessages(sessionKey: string, limit = 50): Message[] {
    const rows = this.stmts.recentMessages.all(sessionKey, limit) as Record<string, unknown>[];
    return rows.map((row) => this.rowToMessage(row));
  }

  // -----------------------------------------------------------------------
  // User profile
  // -----------------------------------------------------------------------

  /**
   * Retrieve a user profile by ID.
   */
  async getUserProfile(userId: string): Promise<UserProfile | null> {
    if (this.redis) {
      try {
        const cached = await this.redis.get(this.cacheKey("user", userId));
        if (cached) {
          return JSON.parse(cached) as UserProfile;
        }
      } catch {
        // Fall through.
      }
    }

    const row = this.stmts.getUser.get(userId) as Record<string, unknown> | undefined;
    if (!row) {
      return null;
    }
    const profile = this.rowToUserProfile(row);
    await this.cacheSet("user", userId, profile);
    return profile;
  }

  /**
   * Merge new preferences into an existing user profile.
   * Creates the user if it does not exist.
   */
  async updateUserPreferences(userId: string, preferences: Record<string, unknown>): Promise<void> {
    // Ensure user exists with a stub row.
    this.stmts.insertUser.run(userId, "", "", "{}");

    // Read current preferences to merge.
    const existing = this.stmts.getUser.get(userId) as Record<string, unknown> | undefined;
    const current = existing?.preferences
      ? (JSON.parse(existing.preferences as string) as Record<string, unknown>)
      : {};
    const merged = { ...current, ...preferences };

    this.stmts.updateUserPrefs.run(JSON.stringify(merged), userId);

    await this.cacheInvalidate("user", userId);
  }

  // -----------------------------------------------------------------------
  // Context key-value store
  // -----------------------------------------------------------------------

  /**
   * Read all context entries for a session.
   */
  getSessionContext(sessionKey: string): ContextEntry[] {
    const rows = this.stmts.getContext.all(sessionKey) as Record<string, unknown>[];
    return rows.map((row) => ({
      session_key: row.session_key as string,
      key: row.key as string,
      value: row.value as string,
      updated_at: row.updated_at as string,
    }));
  }

  /**
   * Upsert a context value for a session.
   */
  setSessionContext(sessionKey: string, key: string, value: string): void {
    this.stmts.upsertContext.run(sessionKey, key, value);
  }

  // -----------------------------------------------------------------------
  // Vision memory
  // -----------------------------------------------------------------------

  /**
   * Persist a glasses capture with its AI-generated description and tags.
   */
  saveVisionMemory(
    deviceId: string,
    sessionKey: string,
    queryType: string,
    imageHash: string,
    description: string,
    tags: string,
    costUsd: number,
  ): VisionMemory {
    const id = crypto.randomUUID();
    this.stmts.insertVision.run(
      id,
      deviceId,
      sessionKey,
      queryType,
      imageHash,
      description,
      tags,
      costUsd,
    );
    return {
      id,
      device_id: deviceId,
      session_key: sessionKey,
      query_type: queryType,
      image_hash: imageHash,
      description,
      tags,
      created_at: new Date().toISOString(),
      cost_usd: costUsd,
    };
  }

  /**
   * Search vision memories by description or tags using LIKE.
   * Optionally scoped to a specific device.
   */
  recallVision(query: string, deviceId?: string, limit = 20): VisionMemory[] {
    const pattern = `%${query}%`;
    const rows = this.stmts.searchVision.all(
      pattern,
      pattern,
      deviceId ?? null,
      deviceId ?? null,
      limit,
    ) as Record<string, unknown>[];
    return rows.map((row) => this.rowToVisionMemory(row));
  }

  /**
   * Return the most recent vision captures for a device (newest first).
   */
  getRecentVision(deviceId: string, limit = 20): VisionMemory[] {
    const rows = this.stmts.recentVision.all(deviceId, limit) as Record<string, unknown>[];
    return rows.map((row) => this.rowToVisionMemory(row));
  }

  /**
   * Delete all vision memories for a device — privacy cleanup.
   */
  deleteVisionMemories(deviceId: string): number {
    const info = this.stmts.deleteVision.run(deviceId);
    return (info as unknown as { changes: number }).changes;
  }

  // -----------------------------------------------------------------------
  // Cleanup
  // -----------------------------------------------------------------------

  /**
   * Close the underlying SQLite database. Call when shutting down.
   */
  close(): void {
    this.db.close();
  }

  // -----------------------------------------------------------------------
  // Redis helpers
  // -----------------------------------------------------------------------

  private cacheKey(namespace: string, id: string): string {
    return `${REDIS_PREFIX}${namespace}:${id}`;
  }

  private async cacheSet(namespace: string, id: string, data: unknown): Promise<void> {
    if (!this.redis) {
      return;
    }
    try {
      await this.redis.set(this.cacheKey(namespace, id), JSON.stringify(data), {
        ex: this.cacheTtl,
      });
    } catch {
      // Cache write failure is non-fatal.
    }
  }

  private async cacheInvalidate(namespace: string, id: string): Promise<void> {
    if (!this.redis) {
      return;
    }
    try {
      await this.redis.del(this.cacheKey(namespace, id));
    } catch {
      // Cache delete failure is non-fatal.
    }
  }

  // -----------------------------------------------------------------------
  // Row mappers
  // -----------------------------------------------------------------------

  private rowToSession(row: Record<string, unknown>): Session {
    return {
      id: row.id as string,
      user_id: row.user_id as string,
      session_key: row.session_key as string,
      channel: row.channel as string,
      started_at: row.started_at as string,
      last_active_at: row.last_active_at as string,
      metadata: row.metadata ? JSON.parse(row.metadata as string) : {},
    };
  }

  private rowToMessage(row: Record<string, unknown>): Message {
    return {
      id: row.id as number,
      session_key: row.session_key as string,
      role: row.role as string,
      content: row.content as string,
      tokens: row.tokens as number,
      cost: row.cost as number,
      created_at: row.created_at as string,
    };
  }

  private rowToVisionMemory(row: Record<string, unknown>): VisionMemory {
    return {
      id: row.id as string,
      device_id: row.device_id as string,
      session_key: row.session_key as string,
      query_type: row.query_type as string,
      image_hash: row.image_hash as string,
      description: row.description as string,
      tags: (row.tags as string) ?? "",
      created_at: row.created_at as string,
      cost_usd: row.cost_usd as number,
    };
  }

  private rowToUserProfile(row: Record<string, unknown>): UserProfile {
    return {
      id: row.id as string,
      display_name: row.display_name as string,
      channel: row.channel as string,
      preferences: row.preferences ? JSON.parse(row.preferences as string) : {},
      created_at: row.created_at as string,
      updated_at: row.updated_at as string,
    };
  }
}
