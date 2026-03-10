# Event Trigger System - Quick Reference Card

## Import & Setup

```typescript
import {
  getTriggerEngine,
  handleQualityGatePassed,
  type QualityGatePassedData,
} from "../events/index.js";

const engine = getTriggerEngine();
```

## Register a Trigger

```typescript
engine.registerTrigger({
  eventType: "quality_gate_passed", // Event name
  condition: (data) => data.allChecks, // Optional: fire only if true
  actions: [handleQualityGatePassed], // Handler(s) to execute
  description: "Deploy on quality pass", // Human-readable description
  priority: "high", // Optional: high|normal|low
});
```

## Emit an Event

```typescript
await engine.emitEvent("quality_gate_passed", {
  projectId: "barber-crm",
  commitSha: "abc123",
  testsPassed: true,
  allChecks: true,
});
```

## Event Types Reference

| Event                 | Data Type               | When Fired              |
| --------------------- | ----------------------- | ----------------------- |
| `quality_gate_passed` | `QualityGatePassedData` | Code checks pass        |
| `test_failed`         | `TestFailedData`        | Integration tests fail  |
| `cost_alert`          | `CostAlertData`         | Spending exceeds limit  |
| `agent_timeout`       | `AgentTimeoutData`      | Agent exceeds timeout   |
| `workflow_completed`  | `WorkflowCompletedData` | Workflow finishes       |
| `build_started`       | `BuildStartedData`      | Build begins            |
| `build_completed`     | `BuildCompletedData`    | Build finishes          |
| `deployment_started`  | `DeploymentStartedData` | Deployment begins       |
| `security_alert`      | `SecurityAlertData`     | Security issue detected |

## Pre-Built Handlers

```typescript
import {
  handleQualityGatePassed, // Auto-deploy
  handleTestFailed, // Alert on test failure
  handleCostAlert, // Alert on cost threshold
  handleAgentTimeout, // Auto-recover agent
  handleWorkflowCompleted, // Track workflow
  handleBuildStarted, // Log build start
  handleBuildCompleted, // Deploy on build success
  handleDeploymentStarted, // Monitor deployment
  handleSecurityAlert, // Escalate security
} from "../events/index.js";
```

## Management API

```typescript
// Get all triggers
engine.getTriggers();

// Get triggers for specific event
engine.getTriggers("quality_gate_passed");

// Get count
engine.getTriggerCount("test_failed");

// Get stats
const stats = engine.getStats();
// { totalTriggers: 15, triggersByEvent: {...}, executingCount: 2 }

// Unregister by ID
engine.unregisterTrigger("trigger-id");

// Clear all for an event
engine.clearEvent("test_failed");

// Clear everything
engine.clearAll();
```

## Common Patterns

### Pattern 1: Auto-Deploy on Quality Pass

```typescript
engine.registerTrigger({
  eventType: "quality_gate_passed",
  condition: (data) => data.allChecks && data.testsPassed,
  actions: [handleQualityGatePassed],
  priority: "high",
});
```

### Pattern 2: Graduated Cost Alerts

```typescript
engine.registerTrigger({
  eventType: "cost_alert",
  condition: (data) => data.percentOfLimit > 75,
  actions: [
    async (data) => {
      if (data.percentOfLimit > 95) console.log("CRITICAL");
      else if (data.percentOfLimit > 85) console.log("WARNING");
    },
  ],
  priority: "high",
});
```

### Pattern 3: Multi-Step Workflow

```typescript
engine.registerTrigger({
  eventType: "build_completed",
  condition: (data) => data.success,
  actions: [
    async (data) => console.log("Build succeeded"),
    async (data) => console.log("Running tests"),
    async (data) => console.log("Deploying"),
  ],
  priority: "high",
});
```

### Pattern 4: Custom Condition

```typescript
engine.registerTrigger({
  eventType: "cost_alert",
  condition: (data) => {
    const overage = data.percentOfLimit - 80;
    return overage > 0;
  },
  actions: [handleCostAlert],
  priority: "high",
});
```

## Data Types

### QualityGatePassedData

```typescript
{
  projectId: string;
  commitSha: string;
  testsPassed: boolean;
  allChecks: boolean;
  checkDetails?: Record<string, boolean>;
}
```

### TestFailedData

```typescript
{
  projectId: string;
  testName: string;
  errorMessage: string;
  failureCount: number;
  testFilePath?: string;
  stackTrace?: string;
}
```

### CostAlertData

```typescript
{
  projectId: string;
  dailyCost: number;
  monthlyCost: number;
  dailyLimit: number;
  monthlyLimit: number;
  percentOfLimit: number; // 0-100
  alertLevel: "warning" | "critical";
}
```

### AgentTimeoutData

```typescript
{
  agentId: string;
  taskId: string;
  runningMs: number;
  timeoutMs: number;
  taskName?: string;
}
```

### WorkflowCompletedData

```typescript
{
  workflowId: string;
  projectId: string;
  totalCost: number;
  executionTimeMs: number;
  agentsUsed: string[];
  success: boolean;
  outputPath?: string;
}
```

## Testing

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { TriggerEngine } from "../events/trigger-engine.js";

describe("Custom Trigger", () => {
  let engine: TriggerEngine;

  beforeEach(() => {
    engine = new TriggerEngine();
  });

  it("should deploy on quality gate pass", async () => {
    const calls: any[] = [];

    engine.registerTrigger({
      eventType: "quality_gate_passed",
      condition: (data) => data.allChecks === true,
      actions: [async (data) => calls.push(data)],
      description: "Deploy on pass",
    });

    await engine.emitEvent("quality_gate_passed", {
      projectId: "test",
      commitSha: "abc123",
      testsPassed: true,
      allChecks: true,
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(calls).toHaveLength(1);
  });
});
```

## Tips & Tricks

### Tip 1: No-Op Condition

Don't provide condition if you want trigger to always fire:

```typescript
// This trigger fires for every cost_alert event
engine.registerTrigger({
  eventType: "cost_alert",
  actions: [handleCostAlert],
  // No condition = always fire
});
```

### Tip 2: Condition Shorthand

Use arrow function for simple conditions:

```typescript
condition: (data) => data.severity === "critical";
```

### Tip 3: Error Handling

Errors are logged but don't crash the system:

```typescript
// Safe to throw - won't crash other actions
actions: [
  async () => {
    throw new Error("Safe error");
  },
  async () => {
    console.log("Still runs");
  },
];
```

### Tip 4: Priority Order

Register high-priority triggers that should run first:

```typescript
engine.registerTrigger({
  priority: "high", // Runs first
  // ...
});

engine.registerTrigger({
  priority: "low", // Runs last
  // ...
});
```

### Tip 5: Performance

If you have many triggers, use conditions to filter:

```typescript
// Instead of checking in action
condition: (data) => data.percentOfLimit > 75,  // Filter early
actions: [handleCostAlert]
```

## Debugging

### View All Triggers

```typescript
console.log(engine.getTriggers());
```

### View Statistics

```typescript
const stats = engine.getStats();
console.log(`Total: ${stats.totalTriggers}`);
console.log(`Executing: ${stats.executingCount}`);
console.log(`By event:`, stats.triggersByEvent);
```

### Check Trigger Count

```typescript
const count = engine.getTriggerCount("quality_gate_passed");
console.log(`${count} triggers for quality_gate_passed`);
```

### Clear for Testing

```typescript
engine.clearAll(); // Remove all triggers
```

## Performance Notes

- Events are non-blocking (async)
- Max 10 concurrent trigger executions
- Actions execute sequentially within a trigger
- Condition evaluation is fast (should be sync)
- Handlers should complete in <5 seconds

## Common Mistakes

❌ **Wrong:** Forgetting to await event emission

```typescript
engine.emitEvent("event", data); // Don't forget await
```

✅ **Right:**

```typescript
await engine.emitEvent("event", data);
```

---

❌ **Wrong:** Conditions that throw

```typescript
condition: (data) => data.foo.bar; // Throws if data.foo undefined
```

✅ **Right:**

```typescript
condition: (data) => data.foo?.bar === true;
```

---

❌ **Wrong:** Long-running handlers

```typescript
actions: [
  async (data) => {
    // This takes 10 minutes - bad!
    await expensiveOperation();
  },
];
```

✅ **Right:** Spawn background task

```typescript
actions: [
  async (data) => {
    // Start task, don't wait
    expensiveOperation().catch(console.error);
  },
];
```

## Files

- **README.md** - System overview
- **INTEGRATION.md** - Detailed integration guide
- **example-initialization.ts** - Working examples
- **trigger-engine.ts** - Core implementation
- **event-handlers.ts** - Pre-built handlers
- **trigger.test.ts** - 40 comprehensive tests

## See Also

- `./src/events/README.md` - Full documentation
- `./src/events/INTEGRATION.md` - Integration guide
- `./src/events/example-initialization.ts` - Code examples
