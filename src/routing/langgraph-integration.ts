/**
 * LangGraph Router Integration
 * Bridges LangGraph router with OpenClaw gateway and session management
 *
 * Usage:
 * ```ts
 * const handler = createLangGraphRouterHandler(config, sessionManager);
 * const decision = await handler.route(message, sessionKey);
 * ```
 */

import type { OpenClawConfig } from "../config/config.js";
import type { ResolvedAgentRoute, RoutePeer } from "./resolve-route.js";
import {
  LangGraphRouter,
  createLangGraphRouter,
  type RoutingDecision,
} from "./langgraph-router.js";
import { buildAgentMainSessionKey, type ParsedAgentSessionKey } from "./session-key.js";

/**
 * Session manager interface (compatible with OpenClaw's session system)
 */
export interface SessionManager {
  loadSession(sessionKey: string): Promise<{ messages: Array<{ role: string; content: string }> }>;
  saveSession(sessionKey: string, data: any): Promise<void>;
}

/**
 * LangGraph routing handler
 */
export class LangGraphRoutingHandler {
  private router: LangGraphRouter;
  private cfg: OpenClawConfig;
  private sessionManager?: SessionManager;

  constructor(cfg: OpenClawConfig, router: LangGraphRouter, sessionManager?: SessionManager) {
    this.cfg = cfg;
    this.router = router;
    this.sessionManager = sessionManager;
  }

  /**
   * Main routing method: message → LangGraph analysis → agent decision
   */
  async route(
    message: string,
    sessionKey: string,
    context: {
      channel: string;
      accountId: string;
      peer?: RoutePeer;
    },
  ): Promise<RoutingDecision> {
    // Get or load session history
    const sessionHistory = await this.loadSessionHistory(sessionKey);

    // Route using LangGraph
    const decision = await this.router.route(message, sessionKey, context);

    // Enhance decision with OpenClaw session key format
    const enhancedDecision = this.enhanceDecisionWithSessionKey(decision, sessionKey);

    // Save routing decision to session
    await this.saveRoutingToSession(sessionKey, decision);

    return enhancedDecision;
  }

  /**
   * Convert LangGraph routing decision to OpenClaw ResolvedAgentRoute
   */
  toResolvedAgentRoute(
    decision: RoutingDecision,
    channel: string,
    accountId: string,
  ): ResolvedAgentRoute {
    return {
      agentId: decision.agentId,
      channel,
      accountId,
      sessionKey: decision.sessionKey,
      mainSessionKey: buildAgentMainSessionKey({
        agentId: decision.agentId,
      }).toLowerCase(),
      matchedBy: "default",
    };
  }

  /**
   * Load session history from storage
   */
  private async loadSessionHistory(sessionKey: string): Promise<any> {
    if (!this.sessionManager) {
      return { messages: [] };
    }

    try {
      return await this.sessionManager.loadSession(sessionKey);
    } catch (err) {
      console.warn(`Failed to load session ${sessionKey}:`, err);
      return { messages: [] };
    }
  }

  /**
   * Enhance decision with OpenClaw-specific metadata
   */
  private enhanceDecisionWithSessionKey(
    decision: RoutingDecision,
    sessionKey: string,
  ): RoutingDecision {
    return {
      ...decision,
      sessionKey: buildAgentMainSessionKey({
        agentId: decision.agentId,
      }).toLowerCase(),
    };
  }

  /**
   * Save routing decision to session
   */
  private async saveRoutingToSession(sessionKey: string, decision: RoutingDecision): Promise<void> {
    if (!this.sessionManager) return;

    try {
      const metadata = {
        routing_decision: {
          agentId: decision.agentId,
          agentName: decision.agentName,
          effortLevel: decision.effortLevel,
          confidence: decision.confidence,
          reason: decision.reason,
          timestamp: new Date().toISOString(),
        },
      };

      await this.sessionManager.saveSession(sessionKey, metadata);
    } catch (err) {
      console.warn(`Failed to save routing to session ${sessionKey}:`, err);
    }
  }

  /**
   * Get router statistics
   */
  getStats() {
    return this.router.getStats();
  }
}

/**
 * Factory: Create routing handler from OpenClaw config
 */
export function createLangGraphRoutingHandler(
  cfg: OpenClawConfig,
  sessionManager?: SessionManager,
): LangGraphRoutingHandler {
  const router = createLangGraphRouter(cfg);
  return new LangGraphRoutingHandler(cfg, router, sessionManager);
}

/**
 * Middleware: Integrate LangGraph router into OpenClaw gateway
 *
 * Usage:
 * ```ts
 * const handler = createLangGraphRouterMiddleware(config, sessionManager);
 * // In gateway message handler:
 * const routing = await handler.route(message, sessionKey);
 * ```
 */
export function createLangGraphRouterMiddleware(
  cfg: OpenClawConfig,
  sessionManager?: SessionManager,
) {
  const handler = createLangGraphRoutingHandler(cfg, sessionManager);

  return {
    /**
     * Route a message and return agent + effort level
     */
    async route(
      message: string,
      sessionKey: string,
      channel: string,
      accountId: string,
      peer?: RoutePeer,
    ): Promise<{
      agentId: string;
      agentName: string;
      effortLevel: "low" | "medium" | "high";
      confidence: number;
      selectedSkills: string[];
      fallbackAgentId?: string;
      sessionKey: string;
    }> {
      const decision = await handler.route(message, sessionKey, {
        channel,
        accountId,
        peer,
      });

      return {
        agentId: decision.agentId,
        agentName: decision.agentName,
        effortLevel: decision.effortLevel,
        confidence: decision.confidence,
        selectedSkills: decision.selectedSkills,
        fallbackAgentId: decision.fallbackAgentId,
        sessionKey: decision.sessionKey,
      };
    },

    /**
     * Get current routing stats
     */
    getStats() {
      return handler.getStats();
    },

    /**
     * Clear session state (on disconnect)
     */
    clearSession(sessionKey: string) {
      handler["router"].clearSessionState(sessionKey);
    },
  };
}
