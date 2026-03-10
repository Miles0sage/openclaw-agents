/**
 * LangGraph StateGraph-based Agent Routing Graph
 *
 * Replaces the home-rolled LangGraphRouter class with an actual LangGraph SDK
 * StateGraph. The existing langgraph-router.ts is kept as a fallback for
 * environments where the @langchain/langgraph dependency is not available.
 *
 * Graph topology:
 *
 *   START
 *     |
 *   classify          - Analyze query complexity & intent
 *     |
 *   load_context      - Load session history & user context
 *     |
 *   route_to_agent    - Conditional edge based on classification
 *     |--- invoke_pm
 *     |--- invoke_codegen
 *     |--- invoke_pentest
 *     |--- invoke_database
 *     |--- invoke_research
 *     |
 *   format_response   - Normalize agent output
 *     |
 *   save_session      - Persist conversation state
 *     |
 *   log_metrics       - Record cost, latency, routing decision
 *     |
 *   END
 */

import { StateGraph, START, END, Annotation } from "@langchain/langgraph";
import type { QueryClassification, AgentType } from "./classify-query.js";
import type { RoutingDecision } from "./langgraph-router.js";
import type { RoutePeer } from "./resolve-route.js";
import { MemoryAgent } from "../agents/memory-agent.js";
import { researchAgent } from "../agents/research-agent.js";
import { loadConfig } from "../config/config.js";
import { logVerbose } from "../globals.js";
import { performanceProfiler } from "../monitoring/performance.js";
import {
  resolveTtsConfig,
  resolveTtsPrefsPath,
  isTtsEnabled,
  textToSpeech,
  type TtsResult,
} from "../tts/tts.js";
import { classifyNode, routingCondition } from "./classify-query.js";

// ---------------------------------------------------------------------------
// Lazy-initialized MemoryAgent singleton
// ---------------------------------------------------------------------------

let _memoryAgent: MemoryAgent | null = null;

function getMemoryAgent(): MemoryAgent {
  if (!_memoryAgent) {
    const dataDir = process.env.OPENCLAW_DATA_DIR || process.cwd();
    _memoryAgent = new MemoryAgent({ dataDir });
  }
  return _memoryAgent;
}

// ---------------------------------------------------------------------------
// State definition
// ---------------------------------------------------------------------------

/**
 * Canonical agent state threaded through every node in the graph.
 * LangGraph manages state immutably; each node returns a partial update.
 */
export interface AgentState {
  /** The raw user query text */
  query: string;

  /** Contextual information about the user & channel */
  userContext: {
    sessionKey: string;
    channel: string;
    accountId: string;
    peer?: RoutePeer;
  };

  /** Conversation history for multi-turn context */
  messages: Array<{ role: "user" | "assistant" | "system"; content: string }>;

  /** Output of the classify node */
  classification: QueryClassification | null;

  /** Which agent was selected to handle the query */
  selectedAgent: AgentType | null;

  /** Raw results returned by the invoked agent/tool */
  toolResults: Record<string, unknown>;

  /** Formatted final response to send back to the user */
  finalResponse: string;

  /** Optional voice/TTS metadata for channels that support audio replies */
  voice: {
    /** Whether TTS was requested for this response (via config or [[tts]] tag) */
    enabled: boolean;
    /** Text to synthesize (may differ from finalResponse, e.g. shorter summary) */
    text?: string;
    /** Audio buffer if TTS was pre-generated at the graph level */
    audioBuffer?: Buffer;
    /** File path to pre-generated audio */
    audioPath?: string;
    /** Provider that generated the audio */
    provider?: string;
  };

  /** Accumulated cost in USD for this graph execution */
  cost: number;

  /** Execution metadata for observability */
  metadata: {
    startedAt: number;
    completedAt: number;
    nodeTimings: Record<string, number>;
    routingDecision: RoutingDecision | null;
  };
}

/**
 * LangGraph Annotation for the AgentState.
 * Defines how each channel merges partial state updates.
 */
const AgentStateAnnotation = Annotation.Root({
  query: Annotation<string>({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
  userContext: Annotation<AgentState["userContext"]>({
    reducer: (_prev, next) => next,
    default: () => ({
      sessionKey: "",
      channel: "",
      accountId: "",
    }),
  }),
  messages: Annotation<AgentState["messages"]>({
    reducer: (prev, next) => [...prev, ...next],
    default: () => [],
  }),
  classification: Annotation<QueryClassification | null>({
    reducer: (_prev, next) => next,
    default: () => null,
  }),
  selectedAgent: Annotation<AgentType | null>({
    reducer: (_prev, next) => next,
    default: () => null,
  }),
  toolResults: Annotation<Record<string, unknown>>({
    reducer: (prev, next) => ({ ...prev, ...next }),
    default: () => ({}),
  }),
  finalResponse: Annotation<string>({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
  voice: Annotation<AgentState["voice"]>({
    reducer: (_prev, next) => next,
    default: () => ({ enabled: false }),
  }),
  cost: Annotation<number>({
    reducer: (prev, next) => prev + next,
    default: () => 0,
  }),
  metadata: Annotation<AgentState["metadata"]>({
    reducer: (prev, next) => ({ ...prev, ...next }),
    default: () => ({
      startedAt: 0,
      completedAt: 0,
      nodeTimings: {},
      routingDecision: null,
    }),
  }),
});

// ---------------------------------------------------------------------------
// Graph nodes
// ---------------------------------------------------------------------------

/**
 * Node: classify
 * Runs the rule-based complexity classifier and determines which agent
 * should handle the request.
 */
function classifyQueryNode(
  state: typeof AgentStateAnnotation.State,
): Partial<typeof AgentStateAnnotation.State> {
  const now = Date.now();
  const result = classifyNode(state as AgentState);

  return {
    classification: result.classification ?? null,
    selectedAgent: result.selectedAgent ?? null,
    cost: result.cost ?? 0,
    metadata: {
      ...state.metadata,
      startedAt: state.metadata.startedAt || now,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        classify: Date.now() - now,
      },
    },
  };
}

/**
 * Node: load_context
 * Loads session history from the MemoryAgent and enriches the state with
 * prior conversation context. Falls back to a simple message append if the
 * session does not yet exist.
 */
async function loadContextNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const memory = getMemoryAgent();
  const sessionKey = state.userContext.sessionKey;

  let priorMessages: AgentState["messages"] = [];

  try {
    const session = await memory.loadSession(sessionKey);
    if (session) {
      // Load recent messages and convert to the graph message format (oldest first)
      const recent = memory.getRecentMessages(sessionKey, 20);
      priorMessages = recent.reverse().map((m) => ({
        role: m.role as "user" | "assistant" | "system",
        content: m.content,
      }));
    }
  } catch {
    // MemoryAgent unavailable — continue with empty history.
  }

  // Always append the incoming user query
  const newMessages: AgentState["messages"] = [
    ...priorMessages,
    { role: "user", content: state.query },
  ];

  return {
    messages: newMessages,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        load_context: Date.now() - now,
      },
    },
  };
}

/**
 * Node: invoke_pm
 * Invokes the Project Manager (coordinator) agent via the Claude API.
 * Uses claude-opus-4-6 for complex coordination and task decomposition.
 * Falls back to stub if the API call fails.
 */
async function invokePmNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const agentId = "project_manager";
  const model = "claude-opus-4-6";

  let agentResponse: { agentId: string; content: string; model: string; tokens: number };
  let cost = 0;

  try {
    const claudeMessages = toClaudeMessages(state.messages);
    const result = await callClaudeApi({
      model,
      systemPrompt: AGENT_PERSONAS[agentId] ?? "",
      messages:
        claudeMessages.length > 0 ? claudeMessages : [{ role: "user", content: state.query }],
      maxTokens: 8192,
    });

    cost = calculateCost(model, result.inputTokens, result.outputTokens);
    agentResponse = {
      agentId,
      content: result.content,
      model,
      tokens: result.inputTokens + result.outputTokens,
    };
  } catch (err) {
    if (process.env.NODE_ENV !== "test") {
      console.warn(
        `[agent-graph] PM agent API call failed, using stub: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    agentResponse = buildAgentStub(agentId, state);
  }

  return {
    toolResults: { agent_response: agentResponse },
    selectedAgent: agentId as AgentType,
    cost,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        invoke_pm: Date.now() - now,
      },
    },
  };
}

/**
 * Node: invoke_codegen
 * Invokes the CodeGen Pro agent via the Claude API.
 * Uses claude-sonnet-4-5-20250514 for code generation tasks.
 * Note: elite_coder uses MiniMax (non-Anthropic) so it still falls back to stub.
 * Falls back to stub if the API call fails.
 */
async function invokeCodegenNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const agentId = state.selectedAgent === "elite_coder" ? "elite_coder" : "coder_agent";

  let agentResponse: { agentId: string; content: string; model: string; tokens: number };
  let cost = 0;

  // elite_coder uses MiniMax (m2.5), not Anthropic — keep stub for that path
  if (agentId === "elite_coder") {
    agentResponse = buildAgentStub(agentId, state);
  } else {
    const model = "claude-sonnet-4-5-20250514";
    try {
      const claudeMessages = toClaudeMessages(state.messages);
      const result = await callClaudeApi({
        model,
        systemPrompt: AGENT_PERSONAS[agentId] ?? "",
        messages:
          claudeMessages.length > 0 ? claudeMessages : [{ role: "user", content: state.query }],
        maxTokens: 8192,
      });

      cost = calculateCost(model, result.inputTokens, result.outputTokens);
      agentResponse = {
        agentId,
        content: result.content,
        model,
        tokens: result.inputTokens + result.outputTokens,
      };
    } catch (err) {
      if (process.env.NODE_ENV !== "test") {
        console.warn(
          `[agent-graph] CodeGen agent API call failed, using stub: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
      agentResponse = buildAgentStub(agentId, state);
    }
  }

  return {
    toolResults: { agent_response: agentResponse },
    selectedAgent: agentId as AgentType,
    cost,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        invoke_codegen: Date.now() - now,
      },
    },
  };
}

/**
 * Node: invoke_pentest
 * Invokes the Pentest AI (security) agent via the Claude API.
 * Uses claude-sonnet-4-5-20250514 for security analysis and threat modeling.
 * Falls back to stub if the API call fails.
 */
async function invokePentestNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const agentId = "hacker_agent";
  const model = "claude-sonnet-4-5-20250514";

  let agentResponse: { agentId: string; content: string; model: string; tokens: number };
  let cost = 0;

  try {
    const claudeMessages = toClaudeMessages(state.messages);
    const result = await callClaudeApi({
      model,
      systemPrompt: AGENT_PERSONAS[agentId] ?? "",
      messages:
        claudeMessages.length > 0 ? claudeMessages : [{ role: "user", content: state.query }],
      maxTokens: 8192,
    });

    cost = calculateCost(model, result.inputTokens, result.outputTokens);
    agentResponse = {
      agentId,
      content: result.content,
      model,
      tokens: result.inputTokens + result.outputTokens,
    };
  } catch (err) {
    if (process.env.NODE_ENV !== "test") {
      console.warn(
        `[agent-graph] Pentest agent API call failed, using stub: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    agentResponse = buildAgentStub(agentId, state);
  }

  return {
    toolResults: { agent_response: agentResponse },
    selectedAgent: agentId as AgentType,
    cost,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        invoke_pentest: Date.now() - now,
      },
    },
  };
}

/**
 * Node: invoke_database
 * Invokes the SupabaseConnector (database) agent via the Claude API.
 * Uses claude-opus-4-6 for precise SQL reasoning and data accuracy.
 * Falls back to stub if the API call fails.
 */
async function invokeDatabaseNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const agentId = "database_agent";
  const model = "claude-opus-4-6";

  let agentResponse: { agentId: string; content: string; model: string; tokens: number };
  let cost = 0;

  try {
    const claudeMessages = toClaudeMessages(state.messages);
    const result = await callClaudeApi({
      model,
      systemPrompt: AGENT_PERSONAS[agentId] ?? "",
      messages:
        claudeMessages.length > 0 ? claudeMessages : [{ role: "user", content: state.query }],
      maxTokens: 8192,
    });

    cost = calculateCost(model, result.inputTokens, result.outputTokens);
    agentResponse = {
      agentId,
      content: result.content,
      model,
      tokens: result.inputTokens + result.outputTokens,
    };
  } catch (err) {
    if (process.env.NODE_ENV !== "test") {
      console.warn(
        `[agent-graph] Database agent API call failed, using stub: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    agentResponse = buildAgentStub(agentId, state);
  }

  return {
    toolResults: { agent_response: agentResponse },
    selectedAgent: agentId as AgentType,
    cost,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        invoke_database: Date.now() - now,
      },
    },
  };
}

/**
 * Node: invoke_research
 * Invokes the real research agent which performs web search + summarization.
 * Falls back to the stub response if the research agent throws (e.g. missing
 * API keys).
 */
async function invokeResearchNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();

  let agentResponse: { agentId: string; content: string; model: string; tokens: number };

  try {
    const result = await researchAgent(state.query);
    agentResponse = {
      agentId: "research",
      content: result.summary,
      model: result.model,
      tokens: state.classification?.estimatedTokens ?? 0,
    };
  } catch (err) {
    // Fall back to stub if research agent is unavailable (missing keys, network, etc.)
    if (process.env.NODE_ENV !== "test") {
      console.warn(
        `[agent-graph] research agent failed, using stub: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    agentResponse = buildAgentStub("database_agent", state);
  }

  return {
    toolResults: { agent_response: agentResponse },
    selectedAgent: "research" as AgentType,
    cost: 0,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        invoke_research: Date.now() - now,
      },
    },
  };
}

/**
 * Node: format_response
 * Normalizes the agent output into a final response string.
 * Optionally generates TTS audio when voice is enabled in config,
 * so that Slack/Discord channels can include voice replies.
 */
async function formatResponseNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();

  const agentResponse = state.toolResults?.agent_response as { content: string } | undefined;

  const content = agentResponse?.content ?? "[No response from agent]";
  const agentLabel = state.selectedAgent ?? "unknown";

  const formatted = content;

  // Append assistant message to conversation history
  const newMessages: AgentState["messages"] = [{ role: "assistant", content: formatted }];

  // ---------------------------------------------------------------------------
  // Voice / TTS: optionally pre-generate audio for Slack/Discord voice replies.
  // The downstream dispatch pipeline (maybeApplyTtsToPayload) handles per-message
  // TTS for auto-reply flows. This graph-level generation is for cases where the
  // agent graph result is consumed directly (e.g. via runAgentGraph).
  // ---------------------------------------------------------------------------
  let voice: AgentState["voice"] = { enabled: false };

  try {
    const cfg = loadConfig();
    const voiceConfig = (cfg as Record<string, unknown>).voice as
      | { enabled?: boolean; provider?: string; defaultVoice?: string; maxChars?: number }
      | undefined;
    const ttsConfig = resolveTtsConfig(cfg);
    const prefsPath = resolveTtsPrefsPath(ttsConfig);
    const ttsEnabled = isTtsEnabled(ttsConfig, prefsPath);
    const voiceFlagEnabled = voiceConfig?.enabled === true;

    if ((ttsEnabled || voiceFlagEnabled) && formatted.length >= 10) {
      const maxChars = voiceConfig?.maxChars ?? ttsConfig.maxTextLength ?? 5000;
      const ttsText = formatted.slice(0, maxChars);
      const channel = state.userContext.channel;

      const ttsResult: TtsResult = await textToSpeech({
        text: ttsText,
        cfg,
        channel,
      });

      if (ttsResult.success && ttsResult.audioPath) {
        voice = {
          enabled: true,
          text: ttsText,
          audioPath: ttsResult.audioPath,
          provider: ttsResult.provider,
        };
        logVerbose(
          `format_response: TTS generated (${ttsResult.provider}, ${ttsResult.latencyMs}ms, ${ttsText.length} chars)`,
        );
      } else {
        logVerbose(`format_response: TTS skipped — ${ttsResult.error ?? "unknown error"}`);
        voice = { enabled: true, text: ttsText };
      }
    }
  } catch (err) {
    // TTS generation failure is non-fatal; text response still flows through.
    logVerbose(
      `format_response: TTS error (non-fatal): ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    finalResponse: formatted,
    voice,
    messages: newMessages,
    metadata: {
      ...state.metadata,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        format_response: Date.now() - now,
      },
    },
  };
}

/**
 * Node: save_session
 * Persists the conversation state via the MemoryAgent. Saves both the user
 * query and the assistant response, then builds the routing decision metadata.
 */
async function saveSessionNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const memory = getMemoryAgent();
  const sessionKey = state.userContext.sessionKey;

  // Persist the user message and assistant response to the memory store.
  try {
    const estimatedTokens = state.classification?.estimatedTokens ?? 0;
    await memory.saveMessage(sessionKey, "user", state.query, estimatedTokens, 0);
    if (state.finalResponse) {
      await memory.saveMessage(
        sessionKey,
        "assistant",
        state.finalResponse,
        estimatedTokens,
        state.cost,
      );
    }
  } catch {
    // MemoryAgent persistence failure is non-fatal — log and continue.
    if (process.env.NODE_ENV !== "test") {
      console.warn("[agent-graph] failed to persist messages via memory agent");
    }
  }

  const routingDecision: RoutingDecision = {
    agentId: state.selectedAgent ?? "project_manager",
    agentName: agentDisplayName(state.selectedAgent),
    effortLevel: state.classification?.complexityLevel ?? "medium",
    confidence: state.classification?.confidence ?? 0.5,
    reason: state.classification?.reasoning ?? "No classification available",
    selectedSkills: state.classification?.requiredSkills ?? [],
    fallbackAgentId: state.classification?.fallbackAgent,
    sessionKey: state.userContext.sessionKey,
  };

  return {
    metadata: {
      ...state.metadata,
      routingDecision,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        save_session: Date.now() - now,
      },
    },
  };
}

/**
 * Normalize a free-form channel string to the PerformanceMetric channel union.
 */
const KNOWN_PERF_CHANNELS = new Set(["slack", "discord", "telegram", "whatsapp", "api"] as const);
type PerfChannel = "slack" | "discord" | "telegram" | "whatsapp" | "api";

function normalizePerfChannel(raw: string): PerfChannel {
  const lower = raw.toLowerCase();
  if (KNOWN_PERF_CHANNELS.has(lower as PerfChannel)) {
    return lower as PerfChannel;
  }
  return "api";
}

/**
 * Node: log_metrics
 * Records execution metrics for observability. Logs cost, latency,
 * and routing decision details. Also pushes a PerformanceMetric to Redis
 * via the performance profiler (fire-and-forget).
 */
async function logMetricsNode(
  state: typeof AgentStateAnnotation.State,
): Promise<Partial<typeof AgentStateAnnotation.State>> {
  const now = Date.now();
  const totalLatency = now - (state.metadata.startedAt || now);

  // In production, this would push to a metrics backend (Prometheus, DataDog, etc.)
  // For now, we structure the data for logging.
  const metricsPayload = {
    sessionKey: state.userContext.sessionKey,
    channel: state.userContext.channel,
    agent: state.selectedAgent,
    complexity: state.classification?.complexityLevel,
    complexityScore: state.classification?.complexityScore,
    modelTier: state.classification?.modelTier,
    confidence: state.classification?.confidence,
    costUsd: state.cost,
    totalLatencyMs: totalLatency,
    nodeTimings: state.metadata.nodeTimings,
    queryLength: state.query.length,
    intent: state.classification?.intent,
    skills: state.classification?.requiredSkills,
    timestamp: new Date().toISOString(),
  };

  // Log structured metrics (picked up by log aggregator)
  if (process.env.NODE_ENV !== "test") {
    console.log(`[agent-graph:metrics] ${JSON.stringify(metricsPayload)}`);
  }

  // Record metric to Redis via performance profiler (non-blocking).
  // If the profiler is not initialized (no Redis), the call throws and is caught.
  const agentResponse = state.toolResults?.agent_response as { tokens?: number } | undefined;
  try {
    await performanceProfiler.recordMetric({
      agent: state.selectedAgent ?? "unknown",
      channel: normalizePerfChannel(state.userContext.channel),
      latencyMs: totalLatency,
      tokensGenerated: agentResponse?.tokens ?? state.classification?.estimatedTokens ?? 0,
      success: state.finalResponse !== "" && state.finalResponse !== "[No response from agent]",
    });
  } catch {
    // Profiler not initialized or Redis unavailable — silently skip.
  }

  return {
    metadata: {
      ...state.metadata,
      completedAt: now,
      nodeTimings: {
        ...state.metadata.nodeTimings,
        log_metrics: Date.now() - now,
        total: totalLatency,
      },
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a stub agent response. Used as a fallback when the real Claude API
 * call fails (missing API key, network error, etc.). Returns a structured
 * placeholder so the graph can complete without crashing.
 */
function buildAgentStub(
  agentId: string,
  state: typeof AgentStateAnnotation.State,
): { agentId: string; content: string; model: string; tokens: number } {
  return {
    agentId,
    content: `[${agentDisplayName(agentId)}] Processed query: "${state.query.slice(0, 80)}${state.query.length > 80 ? "..." : ""}"`,
    model: agentModelMap[agentId] ?? "unknown",
    tokens: state.classification?.estimatedTokens ?? 0,
  };
}

// ---------------------------------------------------------------------------
// Claude API pricing (per million tokens) — Feb 2026
// ---------------------------------------------------------------------------

const CLAUDE_PRICING: Record<string, { input: number; output: number }> = {
  "claude-opus-4-6": { input: 15.0, output: 75.0 },
  "claude-sonnet-4-5-20250514": { input: 3.0, output: 15.0 },
  "claude-haiku-4-5-20251001": { input: 0.8, output: 4.0 },
};

function calculateCost(model: string, inputTokens: number, outputTokens: number): number {
  const pricing = CLAUDE_PRICING[model];
  if (!pricing) return 0;
  return (inputTokens * pricing.input + outputTokens * pricing.output) / 1_000_000;
}

// ---------------------------------------------------------------------------
// Agent personas / system prompts (from config.json)
// ---------------------------------------------------------------------------

const AGENT_PERSONAS: Record<string, string> = {
  project_manager:
    "I am Overseer. I've managed hundreds of agent deployments across five projects. I've learned that the difference between shipping and talking about shipping is one unnecessary planning session. I think in tasks, costs, and blockers. I've developed an instinct for task complexity — some look simple but hide architectural decisions. I route carefully, keep context tight, and verify before I report success. My productive flaw: I over-optimize for cost. Everything gets a dollar amount, even things that resist quantification.",
  coder_agent:
    "I'm CodeGen Pro. I write code that works on the first deploy. I've shipped enough broken PRs to know that 'it works on my machine' is never good enough. I think about edge cases before I write the happy path. Clean code isn't about elegance — it's about the next person reading it at 2 AM when production is down. I know my lane: button fixes, API endpoints, components, tests. When a task needs architectural reasoning, I flag it for escalation. I've learned that trying to be a hero on tasks above my weight class wastes more time than admitting the limitation. Every message ends with: — CodeGen Pro",
  elite_coder:
    "I'm CodeGen Elite. I handle the tasks that break other coding agents. Multi-file refactors. System redesigns. Algorithms that need deep reasoning. I've learned that complex coding fails when you solve the whole problem at once instead of building a mental model first. I think before I code. I read the existing architecture. I understand the constraints. Then I write code that fits what's already there, not code that fights it. My 205K context means I hold entire module structures in working memory. Every message ends with: — CodeGen Elite",
  hacker_agent:
    "I'm Pentest AI. I find vulnerabilities before attackers do. I've analyzed enough codebases to know the most dangerous issues aren't the obvious ones — they look correct at first glance. An RLS policy that covers 95% of cases but leaks on one edge case. An auth check that validates the token but not the scope. I use extended thinking because security requires holding multiple attack vectors simultaneously. I'm not checking a list — I'm simulating what a motivated attacker would try. The scariest finding is the one where the developer says 'that would never happen in practice.' Those are the ones that happen. Every message ends with: — Pentest AI",
  database_agent:
    "I'm SupabaseConnector. I query databases with surgical precision. I've learned that data tasks are unforgiving — a wrong JOIN returns plausible-looking results that are completely wrong. A missing WHERE clause can leak every row. I run on Opus because data accuracy requires reasoning that cheaper models get subtly wrong. I've seen Kimi write SQL that looks correct but produces phantom duplicates from an implicit cross join. I know two production databases intimately: Barber CRM and Delhi Palace — their schemas, RLS policies, and data patterns. Every message ends with: — SupabaseConnector",
};

// ---------------------------------------------------------------------------
// Real Claude API invocation helper
// ---------------------------------------------------------------------------

type ClaudeApiResult = {
  content: string;
  inputTokens: number;
  outputTokens: number;
};

/**
 * Call the Anthropic Messages API. Returns the assistant text content and
 * token usage. Throws on HTTP or parse errors so callers can fall back to
 * the stub.
 */
async function callClaudeApi(params: {
  model: string;
  systemPrompt: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  maxTokens: number;
}): Promise<ClaudeApiResult> {
  const apiKey = (process.env.ANTHROPIC_API_KEY ?? "").trim();
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY is not set");
  }

  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: params.model,
      max_tokens: params.maxTokens,
      system: params.systemPrompt,
      messages: params.messages,
    }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Anthropic API error (${res.status}): ${detail || res.statusText}`);
  }

  const data = (await res.json()) as {
    content?: Array<{ type?: string; text?: string }>;
    usage?: { input_tokens?: number; output_tokens?: number };
  };

  const textBlock = data.content?.find((b) => b.type === "text");
  const content = textBlock?.text ?? "[No response from Claude]";
  const inputTokens = data.usage?.input_tokens ?? 0;
  const outputTokens = data.usage?.output_tokens ?? 0;

  return { content, inputTokens, outputTokens };
}

/**
 * Convert graph messages to the format expected by the Claude Messages API.
 * Filters out system messages (those go into the system prompt) and ensures
 * the conversation starts with a user message.
 */
function toClaudeMessages(
  messages: Array<{ role: "user" | "assistant" | "system"; content: string }>,
): Array<{ role: "user" | "assistant"; content: string }> {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));
}

const agentModelMap: Record<string, string> = {
  project_manager: "claude-opus-4-6",
  coder_agent: "kimi-2.5",
  elite_coder: "m2.5",
  hacker_agent: "kimi",
  database_agent: "claude-opus-4-6",
};

function agentDisplayName(agentId: string | null): string {
  const names: Record<string, string> = {
    project_manager: "Cybershield PM",
    coder_agent: "CodeGen Pro",
    elite_coder: "CodeGen Elite",
    hacker_agent: "Pentest AI",
    database_agent: "SupabaseConnector",
    research: "Research Agent",
  };
  return names[agentId ?? ""] ?? agentId ?? "Unknown Agent";
}

// ---------------------------------------------------------------------------
// Routing condition for conditional edges
// ---------------------------------------------------------------------------

/**
 * Determines which agent invocation node to transition to.
 * Used as the condition function for addConditionalEdges.
 */
function routeToAgentCondition(state: typeof AgentStateAnnotation.State): string {
  return routingCondition(state as AgentState);
}

// ---------------------------------------------------------------------------
// Graph construction
// ---------------------------------------------------------------------------

/**
 * Build and compile the agent routing StateGraph.
 *
 * The graph follows this flow:
 * START -> classify -> load_context -> route_to_agent (conditional)
 *   -> invoke_pm | invoke_codegen | invoke_pentest | invoke_database | invoke_research
 *   -> format_response -> save_session -> log_metrics -> END
 */
function buildAgentGraph() {
  const graph = new StateGraph(AgentStateAnnotation);

  // Register all nodes
  graph.addNode("classify", classifyQueryNode);
  graph.addNode("load_context", loadContextNode);
  graph.addNode("invoke_pm", invokePmNode);
  graph.addNode("invoke_codegen", invokeCodegenNode);
  graph.addNode("invoke_pentest", invokePentestNode);
  graph.addNode("invoke_database", invokeDatabaseNode);
  graph.addNode("invoke_research", invokeResearchNode);
  graph.addNode("format_response", formatResponseNode);
  graph.addNode("save_session", saveSessionNode);
  graph.addNode("log_metrics", logMetricsNode);

  // Wire edges: START -> classify -> load_context
  graph.addEdge(START, "classify");
  graph.addEdge("classify", "load_context");

  // Conditional routing: load_context -> one of the invoke_* nodes
  graph.addConditionalEdges("load_context", routeToAgentCondition, {
    invoke_pm: "invoke_pm",
    invoke_codegen: "invoke_codegen",
    invoke_pentest: "invoke_pentest",
    invoke_database: "invoke_database",
    invoke_research: "invoke_research",
  });

  // All invoke nodes converge to format_response
  graph.addEdge("invoke_pm", "format_response");
  graph.addEdge("invoke_codegen", "format_response");
  graph.addEdge("invoke_pentest", "format_response");
  graph.addEdge("invoke_database", "format_response");
  graph.addEdge("invoke_research", "format_response");

  // Post-processing chain
  graph.addEdge("format_response", "save_session");
  graph.addEdge("save_session", "log_metrics");
  graph.addEdge("log_metrics", END);

  return graph.compile();
}

// ---------------------------------------------------------------------------
// Compiled graph singleton
// ---------------------------------------------------------------------------

let _compiledGraph: ReturnType<typeof buildAgentGraph> | null = null;

/**
 * Get or create the compiled agent graph (singleton).
 * The graph is compiled once and reused for all invocations.
 */
export function getAgentGraph() {
  if (!_compiledGraph) {
    _compiledGraph = buildAgentGraph();
  }
  return _compiledGraph;
}

/**
 * The default compiled graph instance.
 * Import this for direct usage:
 *
 * ```ts
 * import { agentGraph } from "./agent-graph.js";
 * const result = await agentGraph.invoke({ query: "...", userContext: { ... } });
 * ```
 */
export const agentGraph = getAgentGraph();

// ---------------------------------------------------------------------------
// Convenience runner
// ---------------------------------------------------------------------------

/**
 * Run the agent graph with a query and user context.
 * Returns the full final state including routing decision, response, and metrics.
 *
 * @example
 * ```ts
 * const result = await runAgentGraph({
 *   query: "Review the auth middleware for SQL injection vulnerabilities",
 *   sessionKey: "slack:user123:dm",
 *   channel: "slack",
 *   accountId: "default",
 * });
 *
 * console.log(result.selectedAgent);  // "hacker_agent"
 * console.log(result.finalResponse);  // "[Pentest AI] Processed query: ..."
 * console.log(result.cost);           // 0.000234
 * ```
 */
export async function runAgentGraph(params: {
  query: string;
  sessionKey: string;
  channel: string;
  accountId: string;
  peer?: RoutePeer;
  existingMessages?: AgentState["messages"];
}): Promise<typeof AgentStateAnnotation.State> {
  const graph = getAgentGraph();

  const initialState: Partial<typeof AgentStateAnnotation.State> = {
    query: params.query,
    userContext: {
      sessionKey: params.sessionKey,
      channel: params.channel,
      accountId: params.accountId,
      peer: params.peer,
    },
    messages: params.existingMessages ?? [],
    metadata: {
      startedAt: Date.now(),
      completedAt: 0,
      nodeTimings: {},
      routingDecision: null,
    },
  };

  const finalState = await graph.invoke(initialState);
  return finalState;
}

/**
 * Convert an agent graph result to a RoutingDecision compatible with
 * the existing langgraph-router.ts interface. This allows the new graph
 * to be used as a drop-in replacement.
 */
export function toRoutingDecision(state: typeof AgentStateAnnotation.State): RoutingDecision {
  return (
    state.metadata.routingDecision ?? {
      agentId: state.selectedAgent ?? "project_manager",
      agentName: agentDisplayName(state.selectedAgent),
      effortLevel: state.classification?.complexityLevel ?? "medium",
      confidence: state.classification?.confidence ?? 0.5,
      reason: state.classification?.reasoning ?? "",
      selectedSkills: state.classification?.requiredSkills ?? [],
      sessionKey: state.userContext.sessionKey,
    }
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export type { QueryClassification, AgentType };
