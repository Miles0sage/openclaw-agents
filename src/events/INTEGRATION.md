# Event Trigger System Integration Guide

The Event Trigger System enables autonomous reactions to workflow events in OpenClaw, allowing automatic deployment, notifications, and recovery actions based on event emissions.

## Quick Start

### 1. Import the TriggerEngine

```typescript
import {
  getTriggerEngine,
  handleQualityGatePassed,
  type QualityGatePassedData,
} from "../events/index.js";

// Get the singleton engine
const triggerEngine = getTriggerEngine();
```

### 2. Register a Trigger

```typescript
triggerEngine.registerTrigger({
  eventType: "quality_gate_passed",
  condition: (data) => data.allChecks === true,
  actions: [handleQualityGatePassed],
  description: "Auto-deploy on quality gate pass",
  priority: "high",
});
```

### 3. Emit Events

```typescript
const data: QualityGatePassedData = {
  projectId: "my-app",
  commitSha: "abc123def456",
  testsPassed: true,
  allChecks: true,
};

await triggerEngine.emitEvent("quality_gate_passed", data);
```

## Gateway Integration

Add to `src/gateway/server.ts` or similar gateway startup file:

```typescript
import { getTriggerEngine } from "../events/index.js";
import {
  handleQualityGatePassed,
  handleTestFailed,
  handleCostAlert,
  handleAgentTimeout,
  handleWorkflowCompleted,
  handleBuildCompleted,
  handleSecurityAlert,
} from "../events/index.js";

export async function initializeEventSystem(): Promise<void> {
  const triggerEngine = getTriggerEngine();

  // Quality Gate Triggers
  triggerEngine.registerTrigger({
    eventType: "quality_gate_passed",
    condition: (data) => data.allChecks === true && data.testsPassed === true,
    actions: [handleQualityGatePassed],
    description: "Auto-deploy when quality gate passes",
    priority: "high",
  });

  // Test Failure Triggers
  triggerEngine.registerTrigger({
    eventType: "test_failed",
    condition: (data) => data.failureCount <= 2, // Only retry on first 2 failures
    actions: [handleTestFailed],
    description: "Alert and track test failures",
    priority: "normal",
  });

  // Cost Alert Triggers
  triggerEngine.registerTrigger({
    eventType: "cost_alert",
    condition: (data) => data.percentOfLimit > 75, // Alert when >75%
    actions: [handleCostAlert],
    description: "Notify on cost threshold",
    priority: "high",
  });

  // Agent Timeout Triggers
  triggerEngine.registerTrigger({
    eventType: "agent_timeout",
    actions: [handleAgentTimeout],
    description: "Auto-recover timed-out agents",
    priority: "high",
  });

  // Workflow Completion Triggers
  triggerEngine.registerTrigger({
    eventType: "workflow_completed",
    actions: [handleWorkflowCompleted],
    description: "Track workflow completion and metrics",
    priority: "normal",
  });

  // Build Completion Triggers
  triggerEngine.registerTrigger({
    eventType: "build_completed",
    condition: (data) => data.success === true,
    actions: [handleBuildCompleted],
    description: "Deploy on successful build",
    priority: "high",
  });

  // Security Alert Triggers
  triggerEngine.registerTrigger({
    eventType: "security_alert",
    condition: (data) => data.severity === "critical",
    actions: [handleSecurityAlert],
    description: "Escalate critical security issues",
    priority: "high",
  });

  console.log("✅ Event trigger system initialized");
}
```

Call this during gateway startup:

```typescript
// In your gateway main function
async function main() {
  // ... other initialization
  await initializeEventSystem();
  // ... rest of startup
}
```

## Event Types

### Quality Gate Events

Fired when code quality checks pass or fail:

```typescript
interface QualityGatePassedData {
  projectId: string;
  commitSha: string;
  testsPassed: boolean;
  allChecks: boolean;
  checkDetails?: Record<string, boolean>;
}

triggerEngine.emitEvent("quality_gate_passed", {
  projectId: "barber-crm",
  commitSha: "abc123",
  testsPassed: true,
  allChecks: true,
  checkDetails: {
    linting: true,
    testing: true,
    coverage: true,
  },
});
```

### Test Failure Events

Fired when integration tests fail:

```typescript
interface TestFailedData {
  projectId: string;
  testName: string;
  errorMessage: string;
  failureCount: number;
  testFilePath?: string;
  stackTrace?: string;
}

triggerEngine.emitEvent("test_failed", {
  projectId: "barber-crm",
  testName: "should book appointment",
  errorMessage: "Timeout: appointment not created",
  failureCount: 1,
  testFilePath: "test/booking.test.ts",
  stackTrace: "at timeout (...",
});
```

### Cost Alert Events

Fired when spending exceeds thresholds:

```typescript
interface CostAlertData {
  projectId: string;
  dailyCost: number;
  monthlyCost: number;
  dailyLimit: number;
  monthlyLimit: number;
  percentOfLimit: number; // 0-100
  alertLevel: "warning" | "critical";
}

triggerEngine.emitEvent("cost_alert", {
  projectId: "barber-crm",
  dailyCost: 25.5,
  monthlyCost: 450.75,
  dailyLimit: 50,
  monthlyLimit: 500,
  percentOfLimit: 90.15,
  alertLevel: "warning",
});
```

### Agent Timeout Events

Fired when an agent exceeds timeout:

```typescript
interface AgentTimeoutData {
  agentId: string;
  taskId: string;
  runningMs: number;
  timeoutMs: number;
  taskName?: string;
}

triggerEngine.emitEvent("agent_timeout", {
  agentId: "pm-agent",
  taskId: "task-123",
  runningMs: 120000,
  timeoutMs: 60000,
  taskName: "Design system architecture",
});
```

### Workflow Completion Events

Fired when workflows finish:

```typescript
interface WorkflowCompletedData {
  workflowId: string;
  projectId: string;
  totalCost: number;
  executionTimeMs: number;
  agentsUsed: string[];
  success: boolean;
  outputPath?: string;
}

triggerEngine.emitEvent("workflow_completed", {
  workflowId: "wf-123",
  projectId: "barber-crm",
  totalCost: 5.25,
  executionTimeMs: 45000,
  agentsUsed: ["pm-agent", "codegen-agent"],
  success: true,
  outputPath: "/output/design.md",
});
```

### Build Events

Fired during build pipeline:

```typescript
// Build started
triggerEngine.emitEvent("build_started", {
  buildId: "build-456",
  projectId: "barber-crm",
  version: "1.2.0",
  triggerSource: "webhook",
});

// Build completed
triggerEngine.emitEvent("build_completed", {
  buildId: "build-456",
  projectId: "barber-crm",
  version: "1.2.0",
  success: true,
  duration: 120,
  artifactUrl: "https://s3.example.com/barber-crm-1.2.0.zip",
});
```

### Deployment Events

Fired during deployment:

```typescript
triggerEngine.emitEvent("deployment_started", {
  deploymentId: "deploy-789",
  projectId: "barber-crm",
  environment: "production",
  version: "1.2.0",
  commitSha: "abc123def456",
});
```

### Security Alert Events

Fired when security issues detected:

```typescript
triggerEngine.emitEvent("security_alert", {
  alertId: "sec-001",
  severity: "critical",
  title: "SQL Injection in login endpoint",
  description: "Unsanitized user input in database query",
  affectedComponent: "api/auth/login",
  cveId: "CVE-2024-12345",
  remediationSteps: ["Parameterize database queries", "Add input validation", "Run security scan"],
});
```

## Custom Event Handlers

Create custom handlers for domain-specific logic:

```typescript
export async function handleDeploymentHealthCheck(data: DeploymentStartedData): Promise<void> {
  console.log(`Starting health checks for ${data.deploymentId}`);

  // Poll health endpoints
  const maxRetries = 5;
  let retries = 0;

  while (retries < maxRetries) {
    try {
      const response = await fetch(`https://${data.environment}.example.com/health`);
      if (response.ok) {
        console.log(`✅ Health check passed for ${data.deploymentId}`);
        return;
      }
    } catch (err) {
      console.log(`Health check attempt ${retries + 1} failed`);
    }

    retries++;
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }

  throw new Error(`Health checks failed for ${data.deploymentId}`);
}

// Register custom handler
triggerEngine.registerTrigger({
  eventType: "deployment_started",
  actions: [handleDeploymentHealthCheck],
  description: "Monitor deployment health",
  priority: "high",
});
```

## Composing Multiple Actions

Chain actions to create workflows:

```typescript
triggerEngine.registerTrigger({
  eventType: "quality_gate_passed",
  condition: (data) => data.allChecks === true,
  actions: [
    // Action 1: Log and notify
    async (data) => {
      console.log(`Quality gate passed: ${data.projectId}`);
      // await notificationService.notify("QA passed");
    },

    // Action 2: Trigger deployment
    async (data) => {
      console.log(`Deploying ${data.projectId}...`);
      // await deploymentService.deploy(data.projectId, data.commitSha);
    },

    // Action 3: Update dashboard
    async (data) => {
      console.log(`Updating dashboard for ${data.projectId}`);
      // await dashboard.updateStatus(data.projectId, "deploying");
    },
  ],
  description: "Complete QA-to-deployment pipeline",
  priority: "high",
});
```

## Conditional Triggers with Complex Logic

```typescript
triggerEngine.registerTrigger({
  eventType: "cost_alert",
  condition: (data) => {
    // Only alert on significant overage
    const overage = data.percentOfLimit - 80;
    return overage > 0;
  },
  actions: [
    async (data) => {
      if (data.percentOfLimit > 95) {
        // Critical: enable cost-cutting mode
        console.log("Enabling cost-cutting mode");
      } else if (data.percentOfLimit > 85) {
        // Warning: notify team
        console.log("Notifying team of cost threshold");
      }
    },
  ],
  description: "Graduated cost alert system",
  priority: "high",
});
```

## Trigger Management

### Get Trigger Statistics

```typescript
const stats = triggerEngine.getStats();
console.log(`Total triggers: ${stats.totalTriggers}`);
console.log(`Triggers by event:`, stats.triggersByEvent);
console.log(`Currently executing: ${stats.executingCount}`);
```

### List Triggers

```typescript
// Get all triggers
const allTriggers = triggerEngine.getTriggers();

// Get triggers for specific event
const qualityGateTriggers = triggerEngine.getTriggers("quality_gate_passed");

// Count triggers
const count = triggerEngine.getTriggerCount("test_failed");
```

### Unregister Triggers

```typescript
// Unregister by ID
const triggerId = "trigger-quality_gate_passed-1234567890-abc123";
const removed = triggerEngine.unregisterTrigger(triggerId);

// Clear all triggers for an event
triggerEngine.clearEvent("test_failed");

// Clear everything
triggerEngine.clearAll();
```

## Error Handling

The event system is resilient to errors:

```typescript
// This won't crash even if handler throws
triggerEngine.registerTrigger({
  eventType: "test_event",
  actions: [
    async () => {
      throw new Error("Handler error!");
    },
    async () => {
      console.log("This still runs despite previous error");
    },
  ],
  description: "Error-resilient trigger",
});

await triggerEngine.emitEvent("test_event", {});
// Errors are logged, but execution continues
```

## Performance Considerations

### Concurrency Control

The engine limits concurrent executions (default: 10 max concurrent):

```typescript
// If more than 10 triggers execute simultaneously,
// later ones queue until earlier ones complete
const manyEvents = Array.from({ length: 50 }, (_, i) => i);
for (const id of manyEvents) {
  await triggerEngine.emitEvent("event", { id });
}
// All 50 fire, but only 10 execute in parallel
```

### Non-Blocking Events

Emitting events doesn't block agent execution:

```typescript
// Fires trigger asynchronously
await triggerEngine.emitEvent("quality_gate_passed", data);

// Agent immediately returns while trigger runs in background
return {
  status: "success",
  message: "Build passed, deployment triggered",
};
```

## Testing

Triggers are fully testable:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { TriggerEngine } from "../events/trigger-engine.js";

describe("Custom Trigger", () => {
  let engine: TriggerEngine;

  beforeEach(() => {
    engine = new TriggerEngine();
  });

  it("should deploy on quality gate pass", async () => {
    const deployments: any[] = [];

    engine.registerTrigger({
      eventType: "quality_gate_passed",
      condition: (data) => data.allChecks === true,
      actions: [async (data) => deployments.push(data)],
      description: "Deploy on pass",
    });

    await engine.emitEvent("quality_gate_passed", {
      projectId: "test",
      commitSha: "abc123",
      testsPassed: true,
      allChecks: true,
    });

    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(deployments).toHaveLength(1);
    expect(deployments[0].projectId).toBe("test");
  });
});
```

## Next Steps

1. **Integration:** Add event emissions to your gateway and workflow engine
2. **Handlers:** Implement domain-specific handlers for your use cases
3. **Monitoring:** Connect handlers to your notification systems (Slack, Telegram, etc.)
4. **Testing:** Add trigger tests to your CI/CD pipeline
5. **Automation:** Expand to more event types (customer alerts, reporting, etc.)

## Architecture

```
User/Agent → Gateway/Router → Event Emission
                                    ↓
                          Trigger Registration
                                    ↓
                          Condition Evaluation
                                    ↓
                          Action Execution (Sequential)
                                    ↓
                          Error Logging & Continuation
```

Events are non-blocking and allow autonomous reactions to occur without delaying the primary workflow.
