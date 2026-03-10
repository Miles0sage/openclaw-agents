/**
 * Knowledge Graph System for PA Worker Memory
 *
 * Implements entity extraction, linking, and relationship management.
 * Uses D1 (SQLite) for storage with no external dependencies.
 *
 * Tables:
 * - entities: Entity nodes (people, places, projects, goals, habits, topics)
 * - entity_relations: Edges between entities (knows, works_on, located_in, etc.)
 *
 * Features:
 * - Regex/heuristic-based entity extraction (no LLM needed)
 * - Automatic entity-memory linking
 * - Graph queries and subgraph retrieval
 * - Context-aware memory discovery via entity relationships
 * - Graph statistics and analytics
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Entity {
  id: string;
  user_id: string;
  name: string;
  entity_type: "person" | "place" | "project" | "goal" | "habit" | "topic";
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Relation {
  id: string;
  from_entity_id: string;
  to_entity_id: string;
  relation_type: "knows" | "works_on" | "located_in" | "related_to" | "depends_on" | "part_of";
  strength: number; // 0-1, higher = more confident
  created_at: string;
  updated_at: string;
}

export interface EntityGraph {
  entities: Entity[];
  relations: Relation[];
}

export interface GraphStats {
  entity_count: number;
  relation_count: number;
  most_connected_entities: Array<{
    entity_id: string;
    entity_name: string;
    connection_count: number;
  }>;
}

export interface ExtractedEntity {
  name: string;
  type: "person" | "place" | "project" | "goal" | "habit" | "topic";
  confidence: number; // 0-1
  context?: string; // surrounding text
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Common English words to exclude from entity extraction
const COMMON_WORDS = new Set([
  "the",
  "a",
  "an",
  "and",
  "or",
  "but",
  "in",
  "on",
  "at",
  "to",
  "for",
  "of",
  "with",
  "is",
  "was",
  "are",
  "been",
  "be",
  "have",
  "has",
  "had",
  "do",
  "does",
  "did",
  "will",
  "would",
  "could",
  "should",
  "may",
  "might",
  "can",
  "by",
  "from",
  "as",
  "that",
  "which",
  "who",
  "what",
  "when",
  "where",
  "why",
  "how",
  "all",
  "each",
  "every",
  "both",
  "few",
  "more",
  "most",
  "other",
  "some",
  "such",
  "no",
  "not",
  "only",
  "same",
  "so",
  "than",
  "too",
  "very",
  "this",
  "that",
  "these",
  "those",
  "my",
  "your",
  "his",
  "her",
  "its",
  "our",
  "their",
  "i",
  "you",
  "he",
  "she",
  "it",
  "we",
  "they",
]);

// Keywords that indicate project/goal types
const PROJECT_KEYWORDS = ["project", "build", "deploy", "launch", "develop", "create", "website"];
const HABIT_KEYWORDS = ["habit", "routine", "daily", "weekly", "practice", "exercise", "workout"];
const GOAL_KEYWORDS = ["goal", "target", "plan", "aim", "want", "need", "achieve"];
const LOCATION_KEYWORDS = ["live", "located", "based", "office", "at", "visit"];

// ---------------------------------------------------------------------------
// Database Setup
// ---------------------------------------------------------------------------

/**
 * Initialize knowledge graph tables. Call once at startup.
 * Safe to call multiple times (uses IF NOT EXISTS).
 */
export async function initializeGraphTables(db: D1Database): Promise<void> {
  try {
    // Entities table
    await db
      .prepare(
        `
      CREATE TABLE IF NOT EXISTS entities (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'topic',
        metadata TEXT DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      )
      `,
      )
      .run();

    // Create indexes for common queries
    await db.prepare(`CREATE INDEX IF NOT EXISTS idx_entities_user ON entities(user_id)`).run();
    await db
      .prepare(`CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(user_id, name)`)
      .run();
    await db
      .prepare(
        `CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_unique ON entities(user_id, name, entity_type)`,
      )
      .run();

    // Entity relations table
    await db
      .prepare(
        `
      CREATE TABLE IF NOT EXISTS entity_relations (
        id TEXT PRIMARY KEY,
        from_entity_id TEXT NOT NULL,
        to_entity_id TEXT NOT NULL,
        relation_type TEXT NOT NULL DEFAULT 'related_to',
        strength REAL DEFAULT 0.5,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (from_entity_id) REFERENCES entities(id),
        FOREIGN KEY (to_entity_id) REFERENCES entities(id)
      )
      `,
      )
      .run();

    // Create indexes for graph traversal
    await db
      .prepare(`CREATE INDEX IF NOT EXISTS idx_relations_from ON entity_relations(from_entity_id)`)
      .run();
    await db
      .prepare(`CREATE INDEX IF NOT EXISTS idx_relations_to ON entity_relations(to_entity_id)`)
      .run();
    await db
      .prepare(
        `CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique ON entity_relations(from_entity_id, to_entity_id, relation_type)`,
      )
      .run();

    // Bridge table: entities to memories
    await db
      .prepare(
        `
      CREATE TABLE IF NOT EXISTS entity_memory_links (
        id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL,
        memory_id TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id),
        UNIQUE(entity_id, memory_id)
      )
      `,
      )
      .run();

    await db
      .prepare(
        `CREATE INDEX IF NOT EXISTS idx_entity_memory_links_entity ON entity_memory_links(entity_id)`,
      )
      .run();
    await db
      .prepare(
        `CREATE INDEX IF NOT EXISTS idx_entity_memory_links_memory ON entity_memory_links(memory_id)`,
      )
      .run();
  } catch (err) {
    console.error("Error initializing graph tables:", err);
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Generate a random ID for entities and relations.
 */
function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).substr(2, 9)}-${crypto
    .getRandomValues(new Uint8Array(4))
    .reduce((s, b) => s + b.toString(16).padStart(2, "0"), "")}`;
}

/**
 * Normalize entity names (lowercase, trim, collapse whitespace).
 */
function normalizeEntityName(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ")
    .replace(/[^\w\s\-\.@]/g, ""); // Remove special chars except @, -, .
}

/**
 * Check if a word is likely a proper noun based on context and capitalization.
 */
function isLikelyProperNoun(word: string, contextBefore?: string): boolean {
  if (!word || word.length < 2) return false;

  const lowerWord = word.toLowerCase();

  // Skip common words
  if (COMMON_WORDS.has(lowerWord)) return false;

  // Must start with capital letter (unless it's @mention or domain)
  const firstChar = word[0];
  if (
    !/[A-Z@]/.test(firstChar) &&
    !word.includes(".") &&
    !word.includes("_")
  ) {
    return false;
  }

  // Skip numbers-only and too short
  if (/^\d+$/.test(word)) return false;

  return true;
}

/**
 * Detect entity type based on context and keywords.
 */
function detectEntityType(
  name: string,
  context: string,
): "person" | "place" | "project" | "goal" | "habit" | "topic" {
  const lowerContext = context.toLowerCase();
  const lowerName = name.toLowerCase();

  // Check for project keywords
  if (PROJECT_KEYWORDS.some((kw) => lowerContext.includes(kw))) {
    return "project";
  }

  // Check for habit keywords
  if (HABIT_KEYWORDS.some((kw) => lowerContext.includes(kw))) {
    return "habit";
  }

  // Check for goal keywords
  if (GOAL_KEYWORDS.some((kw) => lowerContext.includes(kw))) {
    return "goal";
  }

  // Check for location keywords (place indicators)
  if (LOCATION_KEYWORDS.some((kw) => lowerContext.includes(kw))) {
    return "place";
  }

  // @mention pattern suggests person
  if (name.startsWith("@")) {
    return "person";
  }

  // Email domain suggests place/organization
  if (name.includes("@") && name.includes(".")) {
    return "place"; // Treat as organization/place
  }

  // Default to topic
  return "topic";
}

// ---------------------------------------------------------------------------
// Entity Extraction (Regex/Heuristics, No LLM)
// ---------------------------------------------------------------------------

/**
 * Extract entities from text using regex and heuristics.
 * No LLM calls — pure string analysis.
 *
 * Detects:
 * - Capitalized proper nouns
 * - @mentions (e.g., @john)
 * - Email addresses
 * - URLs
 * - Day/time patterns (excluded)
 */
export async function extractEntities(text: string): Promise<ExtractedEntity[]> {
  const entities: ExtractedEntity[] = [];
  const seen = new Set<string>();

  // Skip if text is too short
  if (!text || text.length < 10) {
    return entities;
  }

  // Pattern 1: @mentions
  const mentionPattern = /@[\w\-\.]+/g;
  const mentions = text.match(mentionPattern) || [];
  mentions.forEach((mention) => {
    const normalized = normalizeEntityName(mention);
    if (!seen.has(normalized)) {
      entities.push({
        name: mention,
        type: "person",
        confidence: 0.95,
        context: "mention",
      });
      seen.add(normalized);
    }
  });

  // Pattern 2: Email addresses
  const emailPattern = /[\w\.-]+@[\w\.-]+\.\w+/g;
  const emails = text.match(emailPattern) || [];
  emails.forEach((email) => {
    const normalized = normalizeEntityName(email);
    if (!seen.has(normalized)) {
      entities.push({
        name: email,
        type: "place", // Email domain = organization
        confidence: 0.9,
        context: "email",
      });
      seen.add(normalized);
    }
  });

  // Pattern 3: URLs
  const urlPattern = /https?:\/\/[\w\.-]+\.\w+(?:\/[\w\-\.]*)?/g;
  const urls = text.match(urlPattern) || [];
  urls.forEach((url) => {
    const normalized = normalizeEntityName(url);
    if (!seen.has(normalized)) {
      entities.push({
        name: url,
        type: "place", // URL = organization/project
        confidence: 0.85,
        context: "url",
      });
      seen.add(normalized);
    }
  });

  // Pattern 4: Capitalized proper nouns (word-by-word analysis)
  const words = text.split(/[\s\n\r]+/);
  for (let i = 0; i < words.length; i++) {
    const word = words[i].replace(/[.,;:!?\-\(\)\[\]{}]/g, ""); // Strip punctuation
    const contextBefore = words.slice(Math.max(0, i - 3), i).join(" ");
    const contextAfter = words.slice(i + 1, Math.min(words.length, i + 4)).join(" ");
    const context = `${contextBefore} ${word} ${contextAfter}`;

    if (isLikelyProperNoun(word, contextBefore)) {
      const normalized = normalizeEntityName(word);
      if (!seen.has(normalized)) {
        const type = detectEntityType(word, context);
        entities.push({
          name: word,
          type,
          confidence: 0.7,
          context: context.trim(),
        });
        seen.add(normalized);
      }
    }
  }

  return entities;
}

// ---------------------------------------------------------------------------
// Entity Management
// ---------------------------------------------------------------------------

/**
 * Upsert an entity. Returns the entity ID.
 * If entity already exists (by user_id + name + type), updates it.
 */
async function upsertEntity(
  db: D1Database,
  userId: string,
  entity: ExtractedEntity,
): Promise<string> {
  const id = generateId();
  const now = new Date().toISOString();
  const normalizedName = normalizeEntityName(entity.name);

  // Check if entity exists
  const existing = await db
    .prepare(
      `SELECT id FROM entities WHERE user_id = ? AND name = ? AND entity_type = ?`,
    )
    .bind(userId, normalizedName, entity.type)
    .first<{ id: string }>();

  if (existing) {
    // Update timestamp if exists
    await db
      .prepare(`UPDATE entities SET updated_at = ? WHERE id = ?`)
      .bind(now, existing.id)
      .run();
    return existing.id;
  }

  // Insert new entity
  const metadata = {
    original_name: entity.name,
    extracted_context: entity.context || "",
    extraction_confidence: entity.confidence,
  };

  await db
    .prepare(
      `
    INSERT INTO entities (id, user_id, name, entity_type, metadata, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    `,
    )
    .bind(
      id,
      userId,
      normalizedName,
      entity.type,
      JSON.stringify(metadata),
      now,
      now,
    )
    .run();

  return id;
}

// ---------------------------------------------------------------------------
// Memory-Entity Linking
// ---------------------------------------------------------------------------

/**
 * Extract entities from memory text and link them.
 * Creates entities, links them to the memory, and creates relations between co-occurring entities.
 */
export async function linkMemoryToEntities(
  db: D1Database,
  memoryId: string,
  memoryText: string,
  userId: string,
): Promise<void> {
  try {
    // Extract entities from memory
    const extractedEntities = await extractEntities(memoryText);

    if (extractedEntities.length === 0) {
      return;
    }

    // Upsert entities and collect IDs
    const entityIds: string[] = [];
    for (const entity of extractedEntities) {
      const entityId = await upsertEntity(db, userId, entity);
      entityIds.push(entityId);

      // Link entity to memory
      const linkId = generateId();
      const now = new Date().toISOString();
      try {
        await db
          .prepare(
            `
          INSERT INTO entity_memory_links (id, entity_id, memory_id, created_at)
          VALUES (?, ?, ?, ?)
          `,
          )
          .bind(linkId, entityId, memoryId, now)
          .run();
      } catch {
        // Link might already exist — silently ignore
      }
    }

    // Create relations between co-occurring entities
    for (let i = 0; i < entityIds.length; i++) {
      for (let j = i + 1; j < entityIds.length; j++) {
        const relationId = generateId();
        const now = new Date().toISOString();

        try {
          await db
            .prepare(
              `
            INSERT INTO entity_relations (id, from_entity_id, to_entity_id, relation_type, strength, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            `,
            )
            .bind(
              relationId,
              entityIds[i],
              entityIds[j],
              "related_to",
              0.5, // Default strength for co-occurrence
              now,
              now,
            )
            .run();
        } catch {
          // Relation might already exist — silently ignore
        }
      }
    }
  } catch (err) {
    console.error("Error linking memory to entities:", err);
    // Don't throw — entity linking is best-effort
  }
}

// ---------------------------------------------------------------------------
// Graph Queries
// ---------------------------------------------------------------------------

/**
 * Get the entity graph for a user.
 * Optionally filtered to a specific entity and its neighbors.
 */
export async function getEntityGraph(
  db: D1Database,
  userId: string,
  entityName?: string,
): Promise<EntityGraph> {
  try {
    let entityQuery = `
      SELECT id, user_id, name, entity_type, metadata, created_at, updated_at
      FROM entities
      WHERE user_id = ?
    `;
    const params: unknown[] = [userId];

    if (entityName) {
      const normalized = normalizeEntityName(entityName);
      entityQuery += " AND name = ?";
      params.push(normalized);
    }

    const entitiesResult = await db.prepare(entityQuery).bind(...params).all<Entity>();

    const entities: Entity[] = (entitiesResult.results || []).map((e) => ({
      ...e,
      metadata: typeof e.metadata === "string" ? JSON.parse(e.metadata) : e.metadata,
    }));

    if (entities.length === 0) {
      return { entities: [], relations: [] };
    }

    // If a specific entity is requested, get its neighborhood
    if (entityName) {
      const entityId = entities[0].id;

      // Get all related entities (1-hop)
      const neighborResult = await db
        .prepare(
          `
        SELECT DISTINCT e.id, e.user_id, e.name, e.entity_type, e.metadata, e.created_at, e.updated_at
        FROM entities e
        JOIN entity_relations r ON (
          (r.from_entity_id = ? AND r.to_entity_id = e.id) OR
          (r.to_entity_id = ? AND r.from_entity_id = e.id)
        )
        WHERE e.user_id = ?
        `,
        )
        .bind(entityId, entityId, userId)
        .all<Entity>();

      const neighborEntities = (neighborResult.results || []).map((e) => ({
        ...e,
        metadata: typeof e.metadata === "string" ? JSON.parse(e.metadata) : e.metadata,
      }));

      entities.push(...neighborEntities);

      // Get relations involving these entities
      const relationIds = [entityId, ...neighborEntities.map((e) => e.id)];
      let relationQuery =
        "SELECT * FROM entity_relations WHERE (from_entity_id IN (" +
        relationIds.map(() => "?").join(",") +
        ") OR to_entity_id IN (" +
        relationIds.map(() => "?").join(",") +
        "))";

      const relationsResult = await db
        .prepare(relationQuery)
        .bind(...relationIds, ...relationIds)
        .all<Relation>();

      return {
        entities,
        relations: relationsResult.results || [],
      };
    }

    // Otherwise, get all relations for this user
    const allRelationIds = entities.map((e) => e.id);
    let relationQuery =
      "SELECT * FROM entity_relations WHERE from_entity_id IN (" +
      allRelationIds.map(() => "?").join(",") +
      ")";

    const relationsResult = await db
      .prepare(relationQuery)
      .bind(...allRelationIds)
      .all<Relation>();

    return {
      entities,
      relations: relationsResult.results || [],
    };
  } catch (err) {
    console.error("Error fetching entity graph:", err);
    return { entities: [], relations: [] };
  }
}

// ---------------------------------------------------------------------------
// Smart Context Discovery
// ---------------------------------------------------------------------------

/**
 * Given a query string, find related entity names, then find memories that mention those entities.
 * Returns memory IDs of related memories.
 *
 * Strategy:
 * 1. Extract entities from the query
 * 2. Find matching entities in the graph
 * 3. Find their neighbors (related entities)
 * 4. Get all memories linked to those entities
 */
export async function getRelatedMemories(
  db: D1Database,
  userId: string,
  query: string,
): Promise<string[]> {
  try {
    // Extract entities from the query
    const queryEntities = await extractEntities(query);

    if (queryEntities.length === 0) {
      return [];
    }

    // Find matching entities in the graph
    const matchingEntityIds: string[] = [];
    for (const entity of queryEntities) {
      const normalized = normalizeEntityName(entity.name);
      const existing = await db
        .prepare(`SELECT id FROM entities WHERE user_id = ? AND name = ?`)
        .bind(userId, normalized)
        .first<{ id: string }>();

      if (existing) {
        matchingEntityIds.push(existing.id);
      }
    }

    if (matchingEntityIds.length === 0) {
      return [];
    }

    // Find neighbors of matching entities (1-hop relations)
    let neighborQuery =
      `SELECT DISTINCT e.id FROM entities e
       JOIN entity_relations r ON (
         (r.from_entity_id IN (` +
      matchingEntityIds.map(() => "?").join(",") +
      `) AND r.to_entity_id = e.id) OR
         (r.to_entity_id IN (` +
      matchingEntityIds.map(() => "?").join(",") +
      `) AND r.from_entity_id = e.id)
       )
       WHERE e.user_id = ?`;

    const neighborResult = await db
      .prepare(neighborQuery)
      .bind(...matchingEntityIds, ...matchingEntityIds, userId)
      .all<{ id: string }>();

    const neighborIds = (neighborResult.results || []).map((r) => r.id);
    const allRelatedIds = [...matchingEntityIds, ...neighborIds];

    // Get all memories linked to these entities
    let memoryQuery =
      `SELECT DISTINCT memory_id FROM entity_memory_links
       WHERE entity_id IN (` +
      allRelatedIds.map(() => "?").join(",") +
      `)`;

    const memoryResult = await db
      .prepare(memoryQuery)
      .bind(...allRelatedIds)
      .all<{ memory_id: string }>();

    return (memoryResult.results || []).map((r) => r.memory_id);
  } catch (err) {
    console.error("Error fetching related memories:", err);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

/**
 * Get statistics about the knowledge graph for a user.
 */
export async function getGraphStats(db: D1Database, userId: string): Promise<GraphStats> {
  try {
    // Count entities
    const entityCountResult = await db
      .prepare(`SELECT COUNT(*) as count FROM entities WHERE user_id = ?`)
      .bind(userId)
      .first<{ count: number }>();

    // Count relations
    const relationCountResult = await db
      .prepare(
        `
      SELECT COUNT(*) as count FROM entity_relations
      WHERE from_entity_id IN (SELECT id FROM entities WHERE user_id = ?)
      `,
      )
      .bind(userId)
      .first<{ count: number }>();

    // Get most connected entities
    const connectedResult = await db
      .prepare(
        `
      SELECT
        e.id,
        e.name,
        COUNT(r.id) as connection_count
      FROM entities e
      LEFT JOIN entity_relations r ON (
        e.id = r.from_entity_id OR e.id = r.to_entity_id
      )
      WHERE e.user_id = ?
      GROUP BY e.id
      ORDER BY connection_count DESC
      LIMIT 10
      `,
      )
      .bind(userId)
      .all<{ id: string; name: string; connection_count: number }>();

    return {
      entity_count: entityCountResult?.count || 0,
      relation_count: relationCountResult?.count || 0,
      most_connected_entities: (connectedResult.results || []).map((row) => ({
        entity_id: row.id,
        entity_name: row.name,
        connection_count: row.connection_count,
      })),
    };
  } catch (err) {
    console.error("Error fetching graph stats:", err);
    return {
      entity_count: 0,
      relation_count: 0,
      most_connected_entities: [],
    };
  }
}
