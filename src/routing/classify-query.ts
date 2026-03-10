/**
 * LangGraph-Compatible Query Classification Layer
 * Wraps the existing ComplexityClassifier into a LangGraph-compatible node
 * that produces structured classification output for the agent graph.
 *
 * This module bridges the rule-based ComplexityClassifier with the
 * LangGraph StateGraph, providing:
 * - Structured classification output (agent type, effort, skills)
 * - Intent-to-agent mapping using config.json keywords
 * - Cost-aware model selection
 * - Confidence scoring with fallback thresholds
 */

import type { AgentState } from "./agent-graph.js";
import { ComplexityClassifier, type ClassificationResult } from "./complexity-classifier.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Agent types recognized by the classifier
 */
export type AgentType =
  | "project_manager"
  | "coder_agent"
  | "elite_coder"
  | "hacker_agent"
  | "database_agent"
  | "research";

/**
 * Full classification output consumed by the agent graph
 */
export interface QueryClassification {
  /** Raw complexity score 0-100 */
  complexityScore: number;
  /** Bucketed complexity level */
  complexityLevel: "low" | "medium" | "high";
  /** Recommended Claude model tier */
  modelTier: "haiku" | "sonnet" | "opus";
  /** Primary agent to route to */
  primaryAgent: AgentType;
  /** Fallback agent if primary is unavailable */
  fallbackAgent: AgentType;
  /** Detected intent category */
  intent: string;
  /** Skills required to handle this query */
  requiredSkills: string[];
  /** Confidence in the classification (0-1) */
  confidence: number;
  /** Human-readable reasoning */
  reasoning: string;
  /** Estimated cost in USD */
  estimatedCostUsd: number;
  /** Estimated token usage (input + output) */
  estimatedTokens: number;
}

// ---------------------------------------------------------------------------
// Keyword dictionaries (aligned with config.json routing.keywords)
// ---------------------------------------------------------------------------

const SECURITY_KEYWORDS = [
  "vulnerability",
  "exploit",
  "penetration",
  "audit",
  "xss",
  "csrf",
  "injection",
  "pentest",
  "hack",
  "breach",
  "threat",
  "attack",
  "threat_modeling",
  "malware",
  "payload",
  "sql injection",
  "owasp",
  "cve",
  "ddos",
  "scan",
  "remediation",
  "hardening",
  "zero-day",
  "privilege escalation",
];

const DEVELOPMENT_KEYWORDS = [
  "code",
  "implement",
  "function",
  "fix",
  "bug",
  "api",
  "endpoint",
  "build",
  "typescript",
  "fastapi",
  "python",
  "javascript",
  "react",
  "nextjs",
  "testing",
  "test",
  "deploy",
  "deployment",
  "frontend",
  "backend",
  "full-stack",
  "refactor",
  "refactoring",
  "clean_code",
  "git",
  "repository",
  "json",
  "yaml",
  "xml",
  "rest",
  "graphql",
  "websocket",
  "component",
  "tailwind",
  "docker",
  "kubernetes",
];

const DATABASE_KEYWORDS = [
  "query",
  "fetch",
  "select",
  "insert",
  "update",
  "delete",
  "table",
  "column",
  "columns",
  "row",
  "rows",
  "data",
  "supabase",
  "postgresql",
  "postgres",
  "sql",
  "database",
  "appointments",
  "clients",
  "services",
  "transactions",
  "orders",
  "customers",
  "call_logs",
  "schema",
  "rls",
  "subscription",
  "real_time",
  "join",
  "migration",
  "users",
];

const PLANNING_KEYWORDS = [
  "plan",
  "timeline",
  "schedule",
  "roadmap",
  "strategy",
  "architecture",
  "design",
  "approach",
  "workflow",
  "process",
  "milestone",
  "deadline",
  "estimate",
  "estimation",
  "breakdown",
  "decompose",
  "coordinate",
  "manage",
  "organize",
  "project",
  "phase",
  "sprint",
  "agile",
  "build a full",
  "system with",
  "full system",
  "role-based",
  "session management",
  "access control",
  "authentication",
  "authorization",
  "end-to-end",
  "from scratch",
];

const COMPLEX_CODING_KEYWORDS = [
  "multi-file",
  "refactor entire",
  "redesign",
  "rearchitect",
  "rebuild",
  "system design",
  "migration",
  "full rewrite",
  "complex algorithm",
  "distributed",
  "consensus",
  "fault tolerance",
  "microservice",
  "multi-region",
  "swe-bench",
  "deep reasoning",
];

const RESEARCH_KEYWORDS = [
  "search",
  "research",
  "investigate",
  "explore",
  "compare",
  "benchmark",
  "evaluate",
  "survey",
  "state of the art",
  "literature",
  "paper",
  "study",
  "analysis",
  "report",
  "lookup",
  "web search",
  "latest",
  "news",
];

// ---------------------------------------------------------------------------
// Skill extraction
// ---------------------------------------------------------------------------

const SKILL_MAP: Record<string, string[]> = {
  typescript: ["typescript", "ts", ".ts"],
  python: ["python", "py", "fastapi", "django", ".py"],
  react: ["react", "component", "jsx", "tsx"],
  nextjs: ["next.js", "nextjs", "next"],
  fastapi: ["fastapi", "fast api"],
  postgresql: ["postgres", "postgresql", "pg"],
  supabase: ["supabase"],
  mongodb: ["mongodb", "mongo"],
  docker: ["docker", "dockerfile", "container"],
  kubernetes: ["kubernetes", "k8s", "helm"],
  security: ["security", "auth", "encryption", "owasp", "pentest"],
  testing: ["test", "testing", "vitest", "jest", "playwright", "e2e"],
  tailwind: ["tailwind", "tailwindcss"],
  sql: ["sql", "query", "join", "select"],
};

function extractSkills(query: string): string[] {
  const lower = query.toLowerCase();
  const skills: string[] = [];

  for (const [skill, keywords] of Object.entries(SKILL_MAP)) {
    if (keywords.some((kw) => lower.includes(kw))) {
      skills.push(skill);
    }
  }

  return [...new Set(skills)];
}

// ---------------------------------------------------------------------------
// Intent classification
// ---------------------------------------------------------------------------

interface IntentScore {
  intent: string;
  agent: AgentType;
  score: number;
}

function scoreIntent(query: string): IntentScore[] {
  const lower = query.toLowerCase();

  const score = (keywords: string[]): number => {
    let total = 0;
    for (const kw of keywords) {
      if (kw.includes(" ")) {
        if (lower.includes(kw)) total += 2;
      } else if (kw.length <= 3) {
        const re = new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
        if (re.test(lower)) total += 1;
      } else {
        const re = new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
        if (re.test(lower)) total += 1;
      }
    }
    return total;
  };

  const scores: IntentScore[] = [
    { intent: "security_audit", agent: "hacker_agent", score: score(SECURITY_KEYWORDS) },
    { intent: "development", agent: "coder_agent", score: score(DEVELOPMENT_KEYWORDS) },
    { intent: "database", agent: "database_agent", score: score(DATABASE_KEYWORDS) },
    { intent: "planning", agent: "project_manager", score: score(PLANNING_KEYWORDS) },
    { intent: "complex_coding", agent: "elite_coder", score: score(COMPLEX_CODING_KEYWORDS) },
    { intent: "research", agent: "research", score: score(RESEARCH_KEYWORDS) },
  ];

  return scores.sort((a, b) => b.score - a.score);
}

// ---------------------------------------------------------------------------
// Agent selection logic
// ---------------------------------------------------------------------------

/**
 * Detect whether a query is asking to BUILD multiple components (planning task)
 * rather than audit/analyze existing security.
 */
function isMultiComponentBuildQuery(query: string): boolean {
  const lower = query.toLowerCase();
  const buildVerbs = /\b(build|create|implement|design|develop|set up|construct)\b/;
  const hasBuildIntent = buildVerbs.test(lower);

  // Count distinct component mentions separated by commas, "and", or "with"
  const componentSegments = lower.split(/,\s*|\band\b|\bwith\b/).length;

  return hasBuildIntent && componentSegments >= 3;
}

function selectAgent(
  intentScores: IntentScore[],
  complexityLevel: "low" | "medium" | "high",
  query: string,
  complexityScore: number,
): { primary: AgentType; fallback: AgentType; intent: string } {
  const top = intentScores[0];
  const runner = intentScores.length > 1 ? intentScores[1] : intentScores[0];

  // No clear intent detected -> route to PM as coordinator
  if (!top || top.score === 0) {
    return {
      primary: "project_manager",
      fallback: "coder_agent",
      intent: "general",
    };
  }

  let primary = top.agent;

  // Heuristic: if hacker_agent wins but the query is about BUILDING/CREATING
  // a system (not auditing one), and complexity is high, route to PM instead.
  // Multi-component build queries need coordination, not penetration testing.
  if (primary === "hacker_agent") {
    const lower = query.toLowerCase();
    const buildVerbs = /\b(build|create|implement|design|develop|set up|architect)\b/;
    if (buildVerbs.test(lower) && (complexityScore > 60 || isMultiComponentBuildQuery(query))) {
      primary = "project_manager";
    }
  }

  // If development intent wins but complexity is high, escalate to elite_coder
  if (primary === "coder_agent" && complexityLevel === "high") {
    primary = "elite_coder";
  }

  // Determine fallback: use runner-up agent, or PM as universal fallback
  let fallback: AgentType =
    runner && runner.score > 0 && runner.agent !== primary ? runner.agent : "project_manager";

  // If primary is elite_coder, fallback to regular coder
  if (primary === "elite_coder") {
    fallback = "coder_agent";
  }

  return { primary, fallback, intent: top.intent };
}

// ---------------------------------------------------------------------------
// Main classifier (singleton)
// ---------------------------------------------------------------------------

let _classifier: ComplexityClassifier | null = null;

function getClassifier(): ComplexityClassifier {
  if (!_classifier) {
    _classifier = new ComplexityClassifier();
  }
  return _classifier;
}

/**
 * Classify a query for the LangGraph agent graph.
 * This is the primary entry point used by the `classify` node in agent-graph.ts.
 */
export function classifyQuery(query: string): QueryClassification {
  const classifier = getClassifier();
  const result: ClassificationResult = classifier.classify(query);

  const intentScores = scoreIntent(query);
  const { primary, fallback, intent } = selectAgent(
    intentScores,
    result.model === "haiku" ? "low" : result.model === "sonnet" ? "medium" : "high",
    query,
    result.complexity,
  );

  const requiredSkills = extractSkills(query);

  return {
    complexityScore: result.complexity,
    complexityLevel:
      result.model === "haiku" ? "low" : result.model === "sonnet" ? "medium" : "high",
    modelTier: result.model,
    primaryAgent: primary,
    fallbackAgent: fallback,
    intent,
    requiredSkills,
    confidence: result.confidence,
    reasoning: result.reasoning,
    estimatedCostUsd: result.costEstimate,
    estimatedTokens: result.estimatedTokens,
  };
}

/**
 * LangGraph node function: classifies the query and writes to AgentState.
 * Returns a partial state update (only the fields this node owns).
 */
export function classifyNode(state: AgentState): Partial<AgentState> {
  const classification = classifyQuery(state.query);

  return {
    classification,
    selectedAgent: classification.primaryAgent,
    cost: classification.estimatedCostUsd,
  };
}

/**
 * Determine the routing edge from classification result.
 * Returns the node name to transition to based on the selected agent.
 */
export function routingCondition(state: AgentState): string {
  if (!state.classification) {
    return "invoke_pm"; // safe fallback
  }

  switch (state.selectedAgent) {
    case "project_manager":
      return "invoke_pm";
    case "coder_agent":
    case "elite_coder":
      return "invoke_codegen";
    case "hacker_agent":
      return "invoke_pentest";
    case "database_agent":
      return "invoke_database";
    default:
      return "invoke_pm";
  }
}
