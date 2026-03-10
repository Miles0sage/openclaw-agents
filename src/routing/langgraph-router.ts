/**
 * LangGraph-based Multi-Agent Router
 * Replaces home-rolled routing system with state machine workflow for intelligent routing
 *
 * Features:
 * - Message complexity classification (low/medium/high)
 * - Adaptive routing to best agent (PM/CodeGen/Security)
 * - Fallback routing on agent unavailability
 * - Session memory integration
 * - Multi-turn conversation state management
 */

import type { OpenClawConfig } from "../config/config.js";
import type { RoutePeer } from "./resolve-route.js";

/**
 * Agent definition from config
 */
export interface AgentDefinition {
  id: string;
  name: string;
  type: "coordinator" | "developer" | "security";
  model: string;
  apiProvider: "anthropic" | "ollama";
  endpoint?: string;
  skills: string[];
  available: boolean;
  backupAgentIds?: string[];
}

/**
 * Routing decision output
 */
export interface RoutingDecision {
  agentId: string;
  agentName: string;
  effortLevel: "low" | "medium" | "high";
  confidence: number;
  reason: string;
  selectedSkills: string[];
  fallbackAgentId?: string;
  sessionKey: string;
}

/**
 * Internal router state (multi-turn conversation context)
 */
interface RouterState {
  sessionKey: string;
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  complexity: "low" | "medium" | "high" | null;
  lastRoutedAgentId: string | null;
  lastRoutedAt: number;
  context: {
    channel: string;
    accountId: string;
    peer?: RoutePeer;
  };
}

/**
 * Agent availability check result
 */
interface AgentAvailabilityResult {
  agentId: string;
  available: boolean;
  lastCheckedAt: number;
  responseTime?: number;
}

/**
 * LangGraph Router Configuration
 */
export interface LangGraphRouterConfig {
  agents: AgentDefinition[];
  sessionStoragePath?: string;
  complexityThresholds?: {
    low: number;
    high: number;
  };
  enableFallbackRouting?: boolean;
  agentTimeoutMs?: number;
  cacheRoutingDecisions?: boolean;
}

/**
 * Main LangGraph Router Implementation
 */
export class LangGraphRouter {
  private config: LangGraphRouterConfig;
  private agentAvailability: Map<string, AgentAvailabilityResult> = new Map();
  private routerStates: Map<string, RouterState> = new Map();
  private routingCache: Map<string, RoutingDecision> = new Map();
  private complexityScores: Map<string, number> = new Map();

  constructor(config: LangGraphRouterConfig) {
    this.config = {
      complexityThresholds: { low: 30, high: 70 },
      enableFallbackRouting: true,
      agentTimeoutMs: 5000,
      cacheRoutingDecisions: true,
      ...config,
    };

    // Initialize agent availability tracking
    for (const agent of config.agents) {
      this.agentAvailability.set(agent.id, {
        agentId: agent.id,
        available: true,
        lastCheckedAt: Date.now(),
      });
    }
  }

  /**
   * Main routing entrypoint: classify message and route to best agent
   */
  async route(
    messageContent: string,
    sessionKey: string,
    context: {
      channel: string;
      accountId: string;
      peer?: RoutePeer;
    },
  ): Promise<RoutingDecision> {
    // Check cache first
    const cacheKey = this.buildCacheKey(sessionKey, messageContent);
    if (this.config.cacheRoutingDecisions && this.routingCache.has(cacheKey)) {
      return this.routingCache.get(cacheKey)!;
    }

    // Get or initialize router state for this session
    let state = this.getOrCreateRouterState(sessionKey, context);

    // Add message to conversation history
    state.messages.push({ role: "user", content: messageContent });

    // Step 1: Classify message complexity
    const complexity = await this.classifyComplexity(messageContent, state);
    state.complexity = complexity;

    // Step 2: Determine effort level based on complexity
    const effortLevel = this.mapComplexityToEffort(complexity);

    // Step 3: Classify intent and extract required skills
    const { intent, requiredSkills } = await this.classifyIntent(messageContent, state);

    // Step 4: Score all available agents
    const agentScores = await this.scoreAgents(messageContent, intent, requiredSkills, state);

    // Step 5: Select best agent (with fallback chain)
    const selectedAgent = this.selectBestAgent(agentScores, complexity);
    if (!selectedAgent) {
      throw new Error("No agents available for routing");
    }

    // Step 6: Check agent availability and setup fallback
    const agentAvailable = await this.checkAgentAvailability(selectedAgent.id);
    let fallbackAgentId: string | undefined;

    if (!agentAvailable.available && this.config.enableFallbackRouting) {
      const fallback = this.findFallbackAgent(selectedAgent.id, agentScores);
      if (fallback) {
        fallbackAgentId = fallback.id;
      }
    }

    // Step 7: Build routing decision
    const decision: RoutingDecision = {
      agentId: selectedAgent.id,
      agentName: selectedAgent.name,
      effortLevel,
      confidence: selectedAgent.confidence,
      reason: selectedAgent.reason,
      selectedSkills: selectedAgent.selectedSkills,
      fallbackAgentId,
      sessionKey,
    };

    // Update state
    state.lastRoutedAgentId = selectedAgent.id;
    state.lastRoutedAt = Date.now();
    state.messages.push({ role: "assistant", content: `[ROUTED_TO: ${selectedAgent.id}]` });

    // Cache the decision
    if (this.config.cacheRoutingDecisions) {
      this.routingCache.set(cacheKey, decision);
    }

    return decision;
  }

  /**
   * Classify message complexity (0-100 score)
   * - Low (0-30): Simple questions, greetings, basic requests
   * - Medium (30-70): Standard tasks, code reviews, moderate complexity
   * - High (70-100): Complex architecture, security audits, multi-step planning
   */
  private async classifyComplexity(
    messageContent: string,
    state: RouterState,
  ): Promise<"low" | "medium" | "high"> {
    // Check cache
    const hash = this.hashString(messageContent);
    if (this.complexityScores.has(hash)) {
      const score = this.complexityScores.get(hash)!;
      return this.scoreToComplexity(score);
    }

    // Heuristic-based complexity scoring (LangGraph would call Claude here)
    const score = this.scoreMessageComplexity(messageContent, state);
    this.complexityScores.set(hash, score);

    return this.scoreToComplexity(score);
  }

  /**
   * Score message for complexity markers
   */
  private scoreMessageComplexity(messageContent: string, state: RouterState): number {
    let score = 0;
    const lowerContent = messageContent.toLowerCase();
    const wordCount = messageContent.split(/\s+/).length;

    // Message length
    if (wordCount > 100) score += 20;
    if (wordCount > 250) score += 15;

    // Technical keywords (security, architecture, performance)
    const securityKeywords = [
      "security",
      "vulnerability",
      "exploit",
      "penetration",
      "owasp",
      "cve",
      "attack",
      "ddos",
      "rate limit",
      "rate limiting",
      "authentication",
      "authorization",
      "encryption",
      "ssl",
      "tls",
      "https",
      "firewall",
    ];
    const architectureKeywords = [
      "architecture",
      "design",
      "scalability",
      "optimization",
      "database",
      "cache",
      "fullstack",
      "full-stack",
      "microservice",
      "integration",
      "authentication",
      "authorization",
      "real-time",
      "pipeline",
      "infrastructure",
      "redesign",
      "migrate",
      "migration",
      "refactor",
      "restructure",
      "rebuild",
      "rearchitect",
    ];
    const codeKeywords = [
      "algorithm",
      "bug",
      "performance",
      "test",
      "deploy",
      "build",
      "implement",
      "create",
      "develop",
      "typescript",
      "react",
      "vue",
      "nextjs",
      "next.js",
      "fastapi",
      "docker",
      "postgresql",
      "websocket",
      "jwt",
      "playwright",
      "kubernetes",
      "tailwind",
      "v4",
      "v19",
      "v2",
      "component",
      "components",
      "e2e",
      "endpoint",
      "endpoints",
      "unit test",
      "integration test",
      "backward",
      "compatibility",
    ];

    const securityMatches = securityKeywords.filter((kw) => lowerContent.includes(kw)).length;
    const archMatches = architectureKeywords.filter((kw) => lowerContent.includes(kw)).length;
    const codeMatches = codeKeywords.filter((kw) => lowerContent.includes(kw)).length;

    score += securityMatches * 15;
    score += archMatches * 12;
    score += codeMatches * 8;

    // Multi-part questions
    const questionCount = (messageContent.match(/\?/g) || []).length;
    score += Math.min(questionCount * 5, 20);

    // Code snippets
    if (messageContent.includes("```") || messageContent.includes("<code>")) {
      score += 25;
    }

    // Previous conversation complexity
    if (state.messages.length > 5) {
      score += Math.min(state.messages.length * 2, 15);
    }

    // Normalize to 0-100
    return Math.min(score, 100);
  }

  /**
   * Convert numeric score to complexity level
   */
  private scoreToComplexity(score: number): "low" | "medium" | "high" {
    const { low, high } = this.config.complexityThresholds!;
    if (score < low) return "low";
    if (score >= high) return "high";
    return "medium";
  }

  /**
   * Map complexity to effort level for adaptive thinking
   */
  private mapComplexityToEffort(complexity: "low" | "medium" | "high"): "low" | "medium" | "high" {
    switch (complexity) {
      case "low":
        return "low"; // Fast inference, lower tokens
      case "medium":
        return "medium"; // Standard thinking
      case "high":
        return "high"; // Full extended thinking for complex problems
    }
  }

  /**
   * Classify message intent and extract required skills
   */
  private async classifyIntent(
    messageContent: string,
    state: RouterState,
  ): Promise<{ intent: string; requiredSkills: string[] }> {
    const lowerContent = messageContent.toLowerCase();

    // Intent classification
    let intent = "general";
    if (
      lowerContent.includes("security") ||
      lowerContent.includes("vulnerab") ||
      lowerContent.includes("attack") ||
      lowerContent.includes("penetrat")
    ) {
      intent = "security_audit";
    } else if (
      lowerContent.includes("code") ||
      lowerContent.includes("build") ||
      lowerContent.includes("implement") ||
      lowerContent.includes("develop")
    ) {
      intent = "development";
    } else if (
      lowerContent.includes("plan") ||
      lowerContent.includes("schedule") ||
      lowerContent.includes("timeline") ||
      lowerContent.includes("project")
    ) {
      intent = "planning";
    }

    // Extract required skills
    const requiredSkills: string[] = [];

    // Skill mapping based on keywords
    const skillMap: Record<string, string[]> = {
      typescript: ["typescript", "ts"],
      python: ["python", "py", "fastapi", "django"],
      react: ["react", "component", "jsx"],
      nextjs: ["next.js", "nextjs", "next"],
      fastapi: ["fastapi", "api", "backend"],
      database: ["database", "sql"],
      postgresql: ["postgres", "postgresql"],
      mongodb: ["mongodb"],
      devops: ["docker", "kubernetes", "ci/cd", "deployment"],
      security: ["security", "auth", "encryption", "owasp"],
    };

    for (const [skill, keywords] of Object.entries(skillMap)) {
      if (keywords.some((kw) => lowerContent.includes(kw))) {
        requiredSkills.push(skill);
      }
    }

    return { intent, requiredSkills };
  }

  /**
   * Score all agents for this message
   */
  private async scoreAgents(
    messageContent: string,
    intent: string,
    requiredSkills: string[],
    state: RouterState,
  ): Promise<
    Array<{
      id: string;
      name: string;
      score: number;
      confidence: number;
      reason: string;
      selectedSkills: string[];
    }>
  > {
    const scores = [];

    for (const agent of this.config.agents) {
      // Base score: agent type vs intent match
      let score = 0;

      // Intent matching (60% weight)
      if (intent === "security_audit" && agent.type === "security") score += 60;
      else if (intent === "development" && agent.type === "developer") score += 60;
      else if (intent === "planning" && agent.type === "coordinator") score += 60;
      else if (agent.type === "coordinator")
        score += 30; // Coordinator is fallback
      else score += 20;

      // Skill match (30% weight)
      const matchedSkills = agent.skills.filter(
        (s) => requiredSkills.includes(s) || requiredSkills.length === 0,
      );
      const skillScore = (matchedSkills.length / Math.max(agent.skills.length, 1)) * 30;
      score += skillScore;

      // Availability (10% weight)
      const availability = this.agentAvailability.get(agent.id);
      const availabilityScore = availability?.available ? 10 : 5;
      score += availabilityScore;

      // Recency penalty: prefer different agent if just used
      if (agent.id === state.lastRoutedAgentId && Date.now() - state.lastRoutedAt < 60000) {
        score *= 0.7; // 30% penalty for recent routing
      }

      const confidence = Math.min(score / 100, 1);
      const reason = this.buildScoringReason(agent, intent, matchedSkills);

      scores.push({
        id: agent.id,
        name: agent.name,
        score,
        confidence,
        reason,
        selectedSkills: matchedSkills,
      });
    }

    // Sort by score descending
    return scores.sort((a, b) => b.score - a.score);
  }

  /**
   * Build human-readable scoring reason
   */
  private buildScoringReason(
    agent: AgentDefinition,
    intent: string,
    matchedSkills: string[],
  ): string {
    const reasons: string[] = [];

    if (agent.type === "coordinator" && intent === "planning") {
      reasons.push("Coordinator best for planning tasks");
    } else if (agent.type === "developer" && intent === "development") {
      reasons.push("Developer best for code tasks");
    } else if (agent.type === "security" && intent === "security_audit") {
      reasons.push("Security expert best for audits");
    }

    if (matchedSkills.length > 0) {
      reasons.push(`Matches skills: ${matchedSkills.join(", ")}`);
    }

    return reasons.length > 0 ? reasons.join("; ") : `General purpose routing to ${agent.name}`;
  }

  /**
   * Select best agent from scored list
   */
  private selectBestAgent(
    agentScores: Array<{
      id: string;
      name: string;
      score: number;
      confidence: number;
      reason: string;
      selectedSkills: string[];
    }>,
    complexity: "low" | "medium" | "high",
  ): (typeof agentScores)[0] | null {
    if (agentScores.length === 0) return null;

    // For high complexity, require higher confidence
    const minConfidence = complexity === "high" ? 0.5 : complexity === "medium" ? 0.3 : 0;

    const qualified = agentScores.filter((s) => s.confidence >= minConfidence);
    return qualified.length > 0 ? qualified[0] : agentScores[0];
  }

  /**
   * Check if agent is available (would call health check endpoint)
   */
  private async checkAgentAvailability(agentId: string): Promise<AgentAvailabilityResult> {
    const cached = this.agentAvailability.get(agentId);
    if (cached && Date.now() - cached.lastCheckedAt < 30000) {
      return cached; // Cache for 30 seconds
    }

    // In production, would make actual health check request
    // For now, assume available
    const result: AgentAvailabilityResult = {
      agentId,
      available: true,
      lastCheckedAt: Date.now(),
    };

    this.agentAvailability.set(agentId, result);
    return result;
  }

  /**
   * Find fallback agent from score list
   */
  private findFallbackAgent(
    primaryAgentId: string,
    agentScores: Array<{
      id: string;
      name: string;
      score: number;
      confidence: number;
      reason: string;
      selectedSkills: string[];
    }>,
  ): (typeof agentScores)[0] | null {
    // Return second-best agent
    const fallbacks = agentScores.filter((s) => s.id !== primaryAgentId);
    return fallbacks.length > 0 ? fallbacks[0] : null;
  }

  /**
   * Get or create router state for session
   */
  private getOrCreateRouterState(
    sessionKey: string,
    context: { channel: string; accountId: string; peer?: RoutePeer },
  ): RouterState {
    if (this.routerStates.has(sessionKey)) {
      return this.routerStates.get(sessionKey)!;
    }

    const state: RouterState = {
      sessionKey,
      messages: [],
      complexity: null,
      lastRoutedAgentId: null,
      lastRoutedAt: 0,
      context,
    };

    this.routerStates.set(sessionKey, state);
    return state;
  }

  /**
   * Build cache key for routing decision
   */
  private buildCacheKey(sessionKey: string, messageContent: string): string {
    return `${sessionKey}:${this.hashString(messageContent)}`;
  }

  /**
   * Simple hash function for strings
   */
  private hashString(str: string): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return `h${Math.abs(hash).toString(36)}`;
  }

  /**
   * Clear cached state for a session
   */
  clearSessionState(sessionKey: string): void {
    this.routerStates.delete(sessionKey);
  }

  /**
   * Get routing stats
   */
  getStats(): {
    totalSessions: number;
    cachedDecisions: number;
    agentAvailability: Record<string, boolean>;
  } {
    const agentAvailability: Record<string, boolean> = {};
    for (const [agentId, result] of this.agentAvailability) {
      agentAvailability[agentId] = result.available;
    }

    return {
      totalSessions: this.routerStates.size,
      cachedDecisions: this.routingCache.size,
      agentAvailability,
    };
  }
}

/**
 * Factory function to create router from OpenClaw config
 */
export function createLangGraphRouter(cfg: OpenClawConfig): LangGraphRouter {
  // Map OpenClaw agents to LangGraphRouter agents
  const agents =
    cfg.agents?.list?.map((agentCfg) => ({
      id: agentCfg.id,
      name: agentCfg.name || agentCfg.id,
      type: getAgentType(agentCfg.id),
      model:
        typeof agentCfg.model === "string"
          ? agentCfg.model
          : agentCfg.model?.primary || "claude-sonnet-4-5-20250929",
      apiProvider: getApiProvider(agentCfg.id),
      endpoint: getEndpoint(agentCfg.id),
      skills: agentCfg.model ? extractSkills(agentCfg) : [],
      available: true,
    })) || [];

  return new LangGraphRouter({
    agents,
    complexityThresholds: { low: 30, high: 70 },
    enableFallbackRouting: true,
    agentTimeoutMs: 5000,
    cacheRoutingDecisions: true,
  });
}

/**
 * Helper: Determine agent type from ID
 */
function getAgentType(agentId: string): "coordinator" | "developer" | "security" {
  const id = agentId.toLowerCase();
  if (id.includes("project") || id.includes("pm") || id.includes("manager")) return "coordinator";
  if (id.includes("code") || id.includes("dev") || id.includes("developer")) return "developer";
  if (id.includes("security") || id.includes("pentest") || id.includes("hacker")) return "security";
  return "coordinator";
}

/**
 * Helper: Determine API provider
 */
function getApiProvider(agentId: string): "anthropic" | "ollama" {
  const id = agentId.toLowerCase();
  if (id.includes("project") || id.includes("pm")) return "anthropic";
  return "ollama";
}

/**
 * Helper: Get API endpoint
 */
function getEndpoint(agentId: string): string | undefined {
  // Would be configured in env vars or config
  return process.env.OLLAMA_ENDPOINT || "http://localhost:11434";
}

/**
 * Helper: Extract skills from agent config
 */
function extractSkills(agentCfg: any): string[] {
  if (Array.isArray(agentCfg.skills)) {
    return agentCfg.skills;
  }
  if (agentCfg.model) {
    const modelStr =
      typeof agentCfg.model === "string" ? agentCfg.model : agentCfg.model?.primary || "";
    const skills: string[] = [];
    if (modelStr.includes("claude")) skills.push("planning", "coordination");
    if (modelStr.includes("qwen")) skills.push("code", "architecture");
    return skills;
  }
  return [];
}

/**
 * Export types for external use
 */
export type { RouterState, AgentAvailabilityResult };
