# LangGraph Router Integration Guide

Step-by-step guide to integrate the LangGraph router into OpenClaw's gateway message handling.

## 1. Gateway Integration Points

### Where to Hook In

The LangGraph router should sit between **message receive** and **agent dispatch**:

```
Message Channel (Slack/Telegram/Discord)
    ↓
[MessageHandler]
    ↓
[LangGraph Router] ← NEW
    ↓
[Agent Dispatch]
    ↓
Agent (PM/CodeGen/Security)
```

### Files to Modify

1. **`src/gateway/message-handler.ts`** - Main message handling loop
2. **`src/gateway/agent-dispatch.ts`** - Agent selection and dispatch
3. **`src/gateway/config-loader.ts`** - Initialize router from config
4. **`src/gateway/routes/chat.ts`** - REST API message endpoint

## 2. Initialize Router

### In Gateway Boot

```typescript
// src/gateway/boot.ts

import { createLangGraphRouterMiddleware } from "../routing/langgraph-integration.js";

export async function initializeGateway(config: OpenClawConfig) {
  // ... existing initialization ...

  // Initialize LangGraph router
  const routingMiddleware = createLangGraphRouterMiddleware(config, sessionManager);

  // Store in gateway context
  return {
    config,
    sessionManager,
    routingMiddleware, // NEW
    // ... other gateway services
  };
}
```

## 3. Integrate Into Message Handler

### Update Message Handler

```typescript
// src/gateway/message-handler.ts

import type { LangGraphRoutingHandler } from "../routing/langgraph-integration.js";

export class GatewayMessageHandler {
  private routingMiddleware: ReturnType<typeof createLangGraphRouterMiddleware>;

  constructor(gateway: GatewayContext) {
    this.routingMiddleware = gateway.routingMiddleware;
  }

  async handleChannelMessage(message: string, channel: string, userId: string, sessionKey: string) {
    // Step 1: Use LangGraph router to decide agent
    const routing = await this.routingMiddleware.route(
      message, // Message content for analysis
      sessionKey, // Session for context
      channel, // 'slack', 'telegram', 'discord'
      userId, // Account ID
      // peer info optional
    );

    console.log(`[${channel}] Routing "${message.slice(0, 50)}..."`);
    console.log(`  → Agent: ${routing.agentName}`);
    console.log(`  → Effort: ${routing.effortLevel}`);
    console.log(`  → Confidence: ${(routing.confidence * 100).toFixed(0)}%`);

    // Step 2: Dispatch to selected agent with effort level
    return this.dispatchToAgent(routing, message, sessionKey);
  }

  private async dispatchToAgent(routing: RoutingDecision, message: string, sessionKey: string) {
    const agentConfig = this.gateway.config.agents?.list?.find((a) => a.id === routing.agentId);

    if (!agentConfig) {
      // Fallback to backup agent if primary not found
      if (routing.fallbackAgentId) {
        console.warn(
          `Agent ${routing.agentId} not found, using fallback ${routing.fallbackAgentId}`,
        );
        return this.dispatchToAgent(
          { ...routing, agentId: routing.fallbackAgentId },
          message,
          sessionKey,
        );
      }
      throw new Error(`No agent configuration found for ${routing.agentId}`);
    }

    // Configure inference based on effort level
    const inferenceConfig = this.getInferenceConfig(routing.effortLevel);

    // Call agent with optimized settings
    return this.callAgent(routing.agentId, message, {
      sessionKey,
      model: agentConfig.model,
      maxTokens: inferenceConfig.maxTokens,
      extendedThinking: inferenceConfig.extendedThinking,
      budget: inferenceConfig.budget,
      metadata: {
        routedVia: "langgraph",
        effortLevel: routing.effortLevel,
        confidence: routing.confidence,
        selectedSkills: routing.selectedSkills,
      },
    });
  }

  private getInferenceConfig(effortLevel: "low" | "medium" | "high") {
    const configs = {
      low: {
        maxTokens: 1024,
        extendedThinking: false,
        budget: "economy", // Use Haiku or fastest model
      },
      medium: {
        maxTokens: 4096,
        extendedThinking: "light",
        budget: "standard", // Use standard model
      },
      high: {
        maxTokens: 8192,
        extendedThinking: true,
        budget: "premium", // Use Opus with extended thinking
      },
    };

    return configs[effortLevel];
  }

  private async callAgent(agentId: string, message: string, options: any) {
    // Implementation calls agent via Pi protocol or HTTP
    // Uses effort level to configure inference
    // ...
  }
}
```

## 4. Update REST API Endpoints

### Add Router Stats Endpoint

```typescript
// src/gateway/routes/routing-stats.ts

import { createReadStream } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";

export async function handleRoutingStatsRequest(
  req: IncomingMessage,
  res: ServerResponse,
  routingMiddleware: any,
) {
  const stats = routingMiddleware.getStats();

  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json");
  res.end(
    JSON.stringify(
      {
        timestamp: new Date().toISOString(),
        routing: stats,
      },
      null,
      2,
    ),
  );
}
```

### Update Chat Endpoint

```typescript
// src/gateway/routes/chat.ts (existing)

export async function handleChatRequest(
  req: IncomingMessage,
  res: ServerResponse,
  config: OpenClawConfig,
  routingMiddleware: any, // NEW parameter
) {
  const body = await readJsonBody(req);
  const { message, sessionKey, channel = "api" } = body;

  try {
    // Step 1: Route using LangGraph
    const routing = await routingMiddleware.route(
      message,
      sessionKey,
      channel,
      "default", // accountId
    );

    // Step 2: Store routing decision in response metadata
    const response = {
      routing: {
        agentId: routing.agentId,
        agentName: routing.agentName,
        effortLevel: routing.effortLevel,
        confidence: routing.confidence,
        selectedSkills: routing.selectedSkills,
      },
      // ... agent response
    };

    sendJson(res, 200, response);
  } catch (err) {
    sendJson(res, 500, {
      error: "Routing failed",
      details: String(err),
    });
  }
}
```

## 5. Session Management Integration

### Load/Save Routing Decisions

```typescript
// src/sessions/session-storage.ts

export class SessionStorage {
  async loadSession(sessionKey: string) {
    const filePath = this.getSessionPath(sessionKey);
    const data = await fs.promises.readFile(filePath, "utf-8");
    return JSON.parse(data);
  }

  async saveRoutingDecision(sessionKey: string, routing: RoutingDecision) {
    const sessionPath = this.getSessionPath(sessionKey);
    const session = await this.loadSession(sessionKey);

    // Append routing decision to session metadata
    session.routing_history = session.routing_history || [];
    session.routing_history.push({
      timestamp: new Date().toISOString(),
      agentId: routing.agentId,
      effortLevel: routing.effortLevel,
      confidence: routing.confidence,
    });

    // Keep only last 100 routing decisions
    if (session.routing_history.length > 100) {
      session.routing_history = session.routing_history.slice(-100);
    }

    await fs.promises.writeFile(sessionPath, JSON.stringify(session, null, 2));
  }
}
```

## 6. Monitoring & Analytics

### Track Routing Metrics

```typescript
// src/gateway/routing-metrics.ts

export class RoutingMetrics {
  private metrics = {
    totalMessages: 0,
    byAgent: new Map<string, number>(),
    byComplexity: new Map<string, number>(),
    byEffort: new Map<string, number>(),
    confidenceHistogram: new Array(10).fill(0),
    latencyMs: new Array<number>(),
  };

  recordRouting(decision: RoutingDecision) {
    this.metrics.totalMessages++;

    // Track by agent
    const agentCount = this.metrics.byAgent.get(decision.agentId) || 0;
    this.metrics.byAgent.set(decision.agentId, agentCount + 1);

    // Track by effort level
    const effortCount = this.metrics.byEffort.get(decision.effortLevel) || 0;
    this.metrics.byEffort.set(decision.effortLevel, effortCount + 1);

    // Track confidence histogram
    const confidenceBucket = Math.floor(decision.confidence * 10);
    this.metrics.confidenceHistogram[confidenceBucket]++;
  }

  getMetrics() {
    const totalByAgent: Record<string, number> = {};
    for (const [agent, count] of this.metrics.byAgent) {
      totalByAgent[agent] = count;
    }

    return {
      totalMessages: this.metrics.totalMessages,
      agentDistribution: totalByAgent,
      effortDistribution: Object.fromEntries(this.metrics.byEffort),
      avgConfidence:
        this.metrics.totalMessages > 0
          ? Array.from(
              { length: 10 },
              (_, i) => ((i + 0.5) / 10) * this.metrics.confidenceHistogram[i],
            ).reduce((a, b) => a + b, 0) / this.metrics.totalMessages
          : 0,
    };
  }
}
```

### Expose Metrics Endpoint

```typescript
// In gateway HTTP handler

if (pathname === "/api/gateway/metrics" && req.method === "GET") {
  const metrics = routingMetrics.getMetrics();
  return sendJson(res, 200, {
    timestamp: new Date().toISOString(),
    metrics,
  });
}
```

## 7. Testing Integration

### Test Message Routing

```typescript
// tests/routing-integration.test.ts

describe("Gateway with LangGraph Router", () => {
  it("routes messages through LangGraph", async () => {
    const handler = new GatewayMessageHandler(gateway);

    const response = await handler.handleChannelMessage(
      "Build a Next.js dashboard with PostgreSQL",
      "slack",
      "user123",
      "slack:channel:user123",
    );

    expect(response).toBeDefined();
    expect(response.agentId).toBe("codegen");
    expect(response.effortLevel).toBe("high");
  });

  it("handles agent unavailability with fallback", async () => {
    // Mock CodeGen as unavailable
    // Message should route to CodeGen but include fallback

    const response = await handler.handleChannelMessage(
      "Build a component",
      "slack",
      "user123",
      "slack:channel:user123",
    );

    expect(response.fallbackAgentId).toBeDefined();
  });

  it("respects effort level in inference config", async () => {
    // Low complexity should use economy config
    // High complexity should use premium config

    const lowResponse = await handler.handleChannelMessage(
      "Hello",
      "slack",
      "user123",
      "slack:channel:user123",
    );
    expect(lowResponse.inferenceConfig.budget).toBe("economy");

    const highResponse = await handler.handleChannelMessage(
      "Conduct a full penetration test with detailed OWASP analysis",
      "slack",
      "user123",
      "slack:channel:user123",
    );
    expect(highResponse.inferenceConfig.budget).toBe("premium");
  });
});
```

## 8. Rollout Plan

### Phase 1: Shadow Mode (Week 1)

```typescript
// Run LangGraph router in parallel, don't use routing
const shadowRouting = await routingMiddleware.route(...);
console.log(`[SHADOW] Would route to ${shadowRouting.agentId}`);

// Still use old routing
const decision = resolveAgentRoute(oldParams);
```

### Phase 2: Gradual Rollout (Week 2)

```typescript
// Route 10% of traffic through LangGraph
const useNewRouter = Math.random() < 0.1;

const decision = useNewRouter
  ? await routingMiddleware.route(...)
  : resolveAgentRoute(oldParams);
```

### Phase 3: Full Migration (Week 3)

```typescript
// Use LangGraph for all routing
const decision = await routingMiddleware.route(message, sessionKey, channel, accountId, peer);
```

## 9. Configuration

### Environment Variables

```bash
# Enable LangGraph router
LANGGRAPH_ROUTER_ENABLED=true

# Complexity thresholds
ROUTER_COMPLEXITY_LOW=30
ROUTER_COMPLEXITY_HIGH=70

# Enable caching
ROUTER_CACHE_ENABLED=true

# Agent timeout
ROUTER_AGENT_TIMEOUT_MS=5000

# Effort level token budgets
EFFORT_LOW_TOKENS=1024
EFFORT_MEDIUM_TOKENS=4096
EFFORT_HIGH_TOKENS=8192
```

### Config File

```json
{
  "routing": {
    "enabled": true,
    "type": "langgraph",
    "complexity": {
      "lowThreshold": 30,
      "highThreshold": 70
    },
    "caching": {
      "enabled": true,
      "ttlSeconds": 300
    },
    "effortLevels": {
      "low": {
        "tokens": 1024,
        "thinking": "off"
      },
      "medium": {
        "tokens": 4096,
        "thinking": "light"
      },
      "high": {
        "tokens": 8192,
        "thinking": "extended"
      }
    }
  }
}
```

## 10. Troubleshooting

### Router Always Picks Same Agent

**Problem:** Messages all route to PM regardless of content

**Solution:**

```typescript
// Check complexity scoring
const score = router.scoreMessageComplexity(message, state);
console.log(`Complexity score: ${score}`);

// Verify skill matching
const { intent, requiredSkills } = router.classifyIntent(message);
console.log(`Intent: ${intent}, Skills: ${requiredSkills}`);

// Disable cache to test routing variety
routerConfig.cacheRoutingDecisions = false;
```

### High Routing Latency

**Problem:** Routing takes >100ms per message

**Solution:**

```typescript
// Reduce agent timeout
routerConfig.agentTimeoutMs = 2000; // from 5000

// Enable caching
routerConfig.cacheRoutingDecisions = true;

// Profile complexity classification
console.time("complexity");
const complexity = await router.classifyComplexity(message, state);
console.timeEnd("complexity");
```

### Fallback Not Used

**Problem:** Fallback agent never selected

**Solution:**

```typescript
// Ensure multiple agents in config
if (config.agents.list.length < 2) {
  console.warn("Fallback requires at least 2 agents");
}

// Enable fallback routing
routerConfig.enableFallbackRouting = true;

// Mock agent unavailable for testing
router.agentAvailability.set("codegen", {
  agentId: "codegen",
  available: false,
  lastCheckedAt: Date.now(),
});
```

## Complete Integration Checklist

- [ ] Copy `langgraph-router.ts` to `src/routing/`
- [ ] Copy `langgraph-integration.ts` to `src/routing/`
- [ ] Update gateway boot to initialize router
- [ ] Update message handler to call router
- [ ] Add routing stats endpoint
- [ ] Update chat API endpoint
- [ ] Integrate with session management
- [ ] Add routing metrics collection
- [ ] Add tests for routing integration
- [ ] Deploy in shadow mode (Week 1)
- [ ] Monitor metrics and validate routing
- [ ] Gradually increase router traffic (Week 2)
- [ ] Full migration (Week 3)
- [ ] Document in README and internal docs

## Success Metrics

- **Routing accuracy:** >90% correct agent selection
- **Latency:** <50ms per message (with cache)
- **Cost savings:** 15-20% reduction in token usage (via effort levels)
- **Fallback rate:** <5% of messages need fallback
- **Cache hit rate:** >70% for repeated messages
