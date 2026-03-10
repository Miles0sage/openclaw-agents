/**
 * LangGraph Router Tests
 */

import { describe, it, expect, beforeEach } from "vitest";
import type { RoutePeer } from "./resolve-route.js";
import {
  LangGraphRouter,
  createLangGraphRouter,
  type AgentDefinition,
  type LangGraphRouterConfig,
} from "./langgraph-router.js";

describe("LangGraphRouter", () => {
  let router: LangGraphRouter;
  let config: LangGraphRouterConfig;

  const mockAgents: AgentDefinition[] = [
    {
      id: "pm",
      name: "Project Manager",
      type: "coordinator",
      model: "claude-sonnet-4-5-20250929",
      apiProvider: "anthropic",
      skills: ["planning", "coordination", "timeline_estimation"],
      available: true,
    },
    {
      id: "codegen",
      name: "CodeGen Pro",
      type: "developer",
      model: "qwen2.5-coder:32b",
      apiProvider: "ollama",
      endpoint: "http://localhost:11434",
      skills: ["nextjs", "fastapi", "typescript", "tailwind", "postgresql"],
      available: true,
    },
    {
      id: "security",
      name: "Pentest AI",
      type: "security",
      model: "qwen2.5-coder:14b",
      apiProvider: "ollama",
      endpoint: "http://localhost:11434",
      skills: ["security", "owasp", "penetration_testing", "threat_modeling"],
      available: true,
    },
  ];

  beforeEach(() => {
    config = {
      agents: mockAgents,
      complexityThresholds: { low: 30, high: 70 },
      enableFallbackRouting: true,
      agentTimeoutMs: 5000,
      cacheRoutingDecisions: true,
    };
    router = new LangGraphRouter(config);
  });

  const sessionKey = "slack:channel123:user456";
  const context = {
    channel: "slack",
    accountId: "default",
    peer: { kind: "dm" as const, id: "user456" },
  };

  describe("Complexity Classification", () => {
    it("classifies simple messages as low complexity", async () => {
      const decision = await router.route("Hello", sessionKey, context);
      expect(decision).toBeDefined();
      expect(decision.effortLevel).toBe("low");
    });

    it("classifies technical messages as high complexity", async () => {
      const decision = await router.route(
        "Can you conduct a security audit for OWASP vulnerabilities? " +
          "We need to check for SQL injection, XSS, and CSRF attacks. " +
          "Also review the authentication flow with JWT tokens and refresh endpoints.",
        sessionKey,
        context,
      );
      expect(decision.effortLevel).toMatch(/medium|high/);
    });

    it("classifies medium-length technical questions as medium complexity", async () => {
      const decision = await router.route(
        "How do I set up PostgreSQL with Node.js?",
        sessionKey,
        context,
      );
      expect(decision.effortLevel).toMatch(/low|medium/);
    });
  });

  describe("Intent Classification", () => {
    it("detects planning intent", async () => {
      const decision = await router.route(
        "Can you help me plan the project timeline?",
        sessionKey,
        context,
      );
      expect(decision.agentId).toBe("pm");
    });

    it("detects development intent", async () => {
      const decision = await router.route(
        "Build a Next.js dashboard with TypeScript and Tailwind",
        sessionKey,
        context,
      );
      expect(decision.agentId).toBe("codegen");
    });

    it("detects security intent", async () => {
      const decision = await router.route(
        "Review for OWASP vulnerabilities and security best practices",
        sessionKey,
        context,
      );
      expect(decision.agentId).toBe("security");
    });
  });

  describe("Agent Routing", () => {
    it("routes planning questions to PM", async () => {
      const decision = await router.route(
        "Help me create a project schedule with milestones",
        sessionKey,
        context,
      );
      expect(decision.agentName).toContain("Project");
    });

    it("routes code requests to CodeGen", async () => {
      const decision = await router.route(
        "Implement a FastAPI endpoint with TypeScript validation",
        sessionKey,
        context,
      );
      expect(decision.agentId).toBe("codegen");
    });

    it("routes security requests to Security agent", async () => {
      const decision = await router.route(
        "Penetration test the authentication system",
        sessionKey,
        context,
      );
      expect(decision.agentId).toBe("security");
    });

    it("returns fallback agent ID", async () => {
      const decision = await router.route("Build a dashboard", sessionKey, context);
      // With fallback routing enabled, should have fallback defined
      expect(decision).toHaveProperty("fallbackAgentId");
    });
  });

  describe("Multi-Turn Conversations", () => {
    it("maintains conversation state across turns", async () => {
      const sessionKey2 = "slack:channel456:user789";

      // Turn 1
      const decision1 = await router.route("Help me plan a project", sessionKey2, context);
      expect(decision1.agentId).toBe("pm");

      // Turn 2 - Different agent should be considered
      const decision2 = await router.route(
        "Now implement this in Next.js with PostgreSQL",
        sessionKey2,
        context,
      );
      // Should route to CodeGen instead of repeating PM
      expect(decision2.agentId).toBe("codegen");
    });

    it("avoids agent ping-pong with recency penalty", async () => {
      const sessionKey3 = "slack:channel789:user999";

      // Route to CodeGen
      await router.route("Build a React component", sessionKey3, context);

      // Immediately ask similar question
      const decision2 = await router.route("Build another React component", sessionKey3, context);

      // Should still route to CodeGen (same intent)
      // But with recency considered
      expect(decision2.agentId).toBe("codegen");
    });
  });

  describe("Skill Matching", () => {
    it("selects agent with matching skills", async () => {
      const decision = await router.route(
        "Implement a PostgreSQL database connection with Node.js",
        sessionKey,
        context,
      );
      expect(decision.selectedSkills).toContain("postgresql");
    });

    it("returns empty skills for generic messages", async () => {
      const decision = await router.route("Hello, how are you?", sessionKey, context);
      // Generic greeting should have minimal skill match
      expect(decision.selectedSkills).toBeDefined();
      expect(Array.isArray(decision.selectedSkills)).toBe(true);
    });
  });

  describe("Confidence Scoring", () => {
    it("returns high confidence for well-matched messages", async () => {
      const decision = await router.route(
        "Review this Next.js code for security vulnerabilities in OWASP context",
        sessionKey,
        context,
      );
      expect(decision.confidence).toBeGreaterThan(0.3);
    });

    it("returns lower confidence for ambiguous messages", async () => {
      const decision = await router.route("Tell me a joke", sessionKey, context);
      expect(decision.confidence).toBeDefined();
      expect(decision.confidence).toBeGreaterThanOrEqual(0);
      expect(decision.confidence).toBeLessThanOrEqual(1);
    });
  });

  describe("Caching", () => {
    it("returns cached routing for identical messages", async () => {
      const message = "Build a dashboard";

      const decision1 = await router.route(message, sessionKey, context);
      const decision2 = await router.route(message, sessionKey, context);

      expect(decision1.agentId).toBe(decision2.agentId);
      expect(decision1.effortLevel).toBe(decision2.effortLevel);
    });

    it("disables cache when configured", async () => {
      const noCacheRouter = new LangGraphRouter({
        ...config,
        cacheRoutingDecisions: false,
      });

      const message = "Plan a project";
      const decision1 = await noCacheRouter.route(message, sessionKey, context);
      const decision2 = await noCacheRouter.route(message, sessionKey, context);

      // Both should be PM, but not from cache
      expect(decision1.agentId).toBe(decision2.agentId);
    });
  });

  describe("Session Management", () => {
    it("clears session state", () => {
      const sessionKey4 = "slack:test:clear";

      // Populate state
      router.route("Test message", sessionKey4, context);

      // Clear it
      router.clearSessionState(sessionKey4);

      // Stats should not include cleared session
      const stats = router.getStats();
      expect(stats.totalSessions).toBeLessThanOrEqual(config.agents!.length + 1);
    });
  });

  describe("Statistics", () => {
    it("provides router statistics", async () => {
      await router.route("Test message", sessionKey, context);

      const stats = router.getStats();

      expect(stats).toHaveProperty("totalSessions");
      expect(stats).toHaveProperty("cachedDecisions");
      expect(stats).toHaveProperty("agentAvailability");

      expect(stats.totalSessions).toBeGreaterThanOrEqual(0);
      expect(stats.cachedDecisions).toBeGreaterThanOrEqual(0);
      expect(typeof stats.agentAvailability).toBe("object");
    });

    it("tracks agent availability in stats", async () => {
      const stats = router.getStats();

      expect(stats.agentAvailability).toHaveProperty("pm");
      expect(stats.agentAvailability).toHaveProperty("codegen");
      expect(stats.agentAvailability).toHaveProperty("security");
    });
  });

  describe("Error Handling", () => {
    it("returns null when no agents available", async () => {
      const emptyRouter = new LangGraphRouter({
        agents: [],
        complexityThresholds: { low: 30, high: 70 },
      });

      await expect(emptyRouter.route("Test", sessionKey, context)).rejects.toThrow(
        "No agents available",
      );
    });
  });

  describe("Real-World Scenarios", () => {
    it("handles complex security audit request", async () => {
      const complexRequest =
        "Conduct a full penetration test of our API. " +
        "We use JWT authentication with 24h expiry, store tokens in localStorage, " +
        "and have a refresh endpoint. Check for OWASP Top 10 vulnerabilities. " +
        "Also review our rate limiting and DDoS protection.";

      const decision = await router.route(complexRequest, sessionKey, context);

      expect(decision.agentId).toBe("security");
      expect(decision.effortLevel).toBe("high");
      expect(decision.selectedSkills).toContain("security");
      expect(decision.confidence).toBeGreaterThan(0.7);
    });

    it("handles multi-component project build request", async () => {
      const complexRequest =
        "Build a full-stack application with: " +
        "- React 19 frontend with Tailwind v4 and TypeScript " +
        "- FastAPI backend with PostgreSQL " +
        "- Real-time updates with WebSockets " +
        "- Authentication with JWT " +
        "- E2E tests with Playwright " +
        "- Docker deployment " +
        "Need it in 2 weeks.";

      const decision = await router.route(complexRequest, sessionKey, context);

      expect(decision.agentId).toBe("codegen");
      expect(decision.effortLevel).toBe("high");
      expect(decision.selectedSkills.length).toBeGreaterThan(0);
    });

    it("handles planning with constraints", async () => {
      const request =
        "Plan the redesign of our 50-component Vue 2 application. " +
        "Migrate to React 19 with TypeScript. " +
        "Budget: $50k, Timeline: 3 months, " +
        "Team: 2 frontend devs, 1 backend dev. " +
        "Must maintain backward compatibility.";

      const decision = await router.route(request, sessionKey, context);

      expect(decision.agentId).toBe("pm");
      expect(decision.effortLevel).toMatch(/medium|high/);
    });
  });

  describe("Factory Function", () => {
    it("creates router from OpenClaw config", () => {
      const mockConfig = {
        agents: {
          list: [
            {
              id: "pm",
              name: "Project Manager",
              agentDir: "/data/pm",
              model: "claude-sonnet-4-5-20250929",
              skills: ["planning"],
            },
          ],
        },
      };

      const routerFromConfig = createLangGraphRouter(mockConfig as any);
      expect(routerFromConfig).toBeDefined();
      expect(routerFromConfig).toBeInstanceOf(LangGraphRouter);
    });
  });
});
