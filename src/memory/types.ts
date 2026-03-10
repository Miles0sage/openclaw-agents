/**
 * Memory & Learning Module Types
 * Defines interfaces for persistent client/project knowledge storage
 */

export interface Decision {
  date: string;
  decision: string;
  reason: string;
  outcome?: string;
}

export interface ClientPreferences {
  techStack?: string;
  styling?: string;
  codingStandards?: string;
  brandColors?: {
    primary?: string;
    secondary?: string;
  };
  [key: string]: unknown;
}

export interface ClientMemory {
  clientId: string;
  preferences: ClientPreferences;
  pastDecisions: Decision[];
  skillsToUse: string[];
  lastUpdated: number;
}

export interface ProjectPattern {
  name: string;
  description?: string;
  example?: string;
}

export interface RecentChange {
  date: string;
  change: string;
  file: string;
}

export interface ProjectMemory {
  projectId: string;
  architecture?: string;
  keyFiles: {
    components?: string[];
    api?: string[];
    database?: string[];
    config?: string[];
    [key: string]: string[] | undefined;
  };
  patterns: ProjectPattern[];
  dependencies: Record<string, string>;
  recentChanges: RecentChange[];
  lastModified: number;
}

export interface Skill {
  title: string;
  tags: string[];
  version?: string;
  appliesTo?: string[];
  content: string;
  filePath?: string;
}

export interface MemoryEntry {
  clientId: string;
  projectId?: string;
  clientMemory?: ClientMemory;
  projectMemory?: ProjectMemory;
  skills?: Skill[];
  timestamp: number;
}

export interface MemoryIndex {
  clients: Map<string, ClientMemory>;
  projects: Map<string, ProjectMemory>;
  skills: Skill[];
  lastIndexed: number;
}

/**
 * New-style search results for client/project/skill memory
 * Used by the client-project-skill memory system
 */
export interface MemorySearchResult {
  type: "client" | "project" | "skill";
  id: string;
  title?: string;
  match?: string;
  relevance: number;
}

/**
 * Legacy memory search types (backward compatibility)
 * These types are used by the memory search manager system
 */

export type MemorySource = "memory" | "sessions";

/**
 * Legacy search result from memory search manager
 * Contains file path, line numbers, score, and snippet
 */
export type LegacyMemorySearchResult = {
  path: string;
  startLine: number;
  endLine: number;
  score: number;
  snippet: string;
  source: MemorySource;
  citation?: string;
};

export type MemoryEmbeddingProbeResult = {
  ok: boolean;
  error?: string;
};

export type MemorySyncProgressUpdate = {
  completed: number;
  total: number;
  label?: string;
};

export type MemoryProviderStatus = {
  backend: "builtin" | "qmd";
  provider: string;
  model?: string;
  requestedProvider?: string;
  files?: number;
  chunks?: number;
  dirty?: boolean;
  workspaceDir?: string;
  dbPath?: string;
  extraPaths?: string[];
  sources?: MemorySource[];
  sourceCounts?: Array<{ source: MemorySource; files: number; chunks: number }>;
  cache?: { enabled: boolean; entries?: number; maxEntries?: number };
  fts?: { enabled: boolean; available: boolean; error?: string };
  fallback?: { from: string; reason?: string };
  vector?: {
    enabled: boolean;
    available?: boolean;
    extensionPath?: string;
    loadError?: string;
    dims?: number;
  };
  batch?: {
    enabled: boolean;
    failures: number;
    limit: number;
    wait: boolean;
    concurrency: number;
    pollIntervalMs: number;
    timeoutMs: number;
    lastError?: string;
    lastProvider?: string;
  };
  custom?: Record<string, unknown>;
};

export interface MemorySearchManager {
  search(
    query: string,
    opts?: { maxResults?: number; minScore?: number; sessionKey?: string },
  ): Promise<MemorySearchResult[]>;
  readFile(params: {
    relPath: string;
    from?: number;
    lines?: number;
  }): Promise<{ text: string; path: string }>;
  status(): MemoryProviderStatus;
  sync?(params?: {
    reason?: string;
    force?: boolean;
    progress?: (update: MemorySyncProgressUpdate) => void;
  }): Promise<void>;
  probeEmbeddingAvailability(): Promise<MemoryEmbeddingProbeResult>;
  probeVectorAvailability(): Promise<boolean>;
  close?(): Promise<void>;
}

/**
 * Internal search result from database queries
 * Used by manager.ts and qmd-manager.ts before converting to MemorySearchResult
 */
export interface InternalSearchResult {
  id: string;
  path: string;
  startLine: number;
  endLine: number;
  score: number;
  snippet: string;
  source: "memory" | "sessions";
}
