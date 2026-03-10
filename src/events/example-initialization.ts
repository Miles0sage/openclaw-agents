/**
 * Event System Initialization Example
 * Shows how to set up the trigger system in a gateway or application
 *
 * Usage: Call initializeEventSystem() during application startup
 */

import {
  handleQualityGatePassed,
  handleTestFailed,
  handleCostAlert,
  handleAgentTimeout,
  handleWorkflowCompleted,
  handleBuildStarted,
  handleBuildCompleted,
  handleDeploymentStarted,
  handleSecurityAlert,
} from "./event-handlers.js";
import { getTriggerEngine } from "./trigger-engine.js";

/**
 * Initialize the event trigger system with standard triggers
 * Call this once during application startup
 */
export async function initializeEventSystem(): Promise<void> {
  const engine = getTriggerEngine();

  console.log("Initializing Event Trigger System...");

  // ============================================================================
  // DEPLOYMENT PIPELINE TRIGGERS
  // ============================================================================

  // Quality Gate: Auto-deploy when all checks pass
  engine.registerTrigger({
    eventType: "quality_gate_passed",
    condition: (data) => data.allChecks === true && data.testsPassed === true,
    actions: [handleQualityGatePassed],
    description: "Auto-deploy when quality gate passes",
    priority: "high",
  });

  // Build Started: Log and notify
  engine.registerTrigger({
    eventType: "build_started",
    actions: [handleBuildStarted],
    description: "Track build pipeline start",
    priority: "normal",
  });

  // Build Completed: Deploy on success
  engine.registerTrigger({
    eventType: "build_completed",
    condition: (data) => data.success === true,
    actions: [handleBuildCompleted],
    description: "Trigger deployment on successful build",
    priority: "high",
  });

  // Deployment Started: Monitor health
  engine.registerTrigger({
    eventType: "deployment_started",
    actions: [handleDeploymentStarted],
    description: "Start health monitoring during deployment",
    priority: "normal",
  });

  // ============================================================================
  // TESTING & QUALITY TRIGGERS
  // ============================================================================

  // Test Failed: Alert and track
  engine.registerTrigger({
    eventType: "test_failed",
    condition: (data) => data.failureCount <= 3, // Only alert on first 3 failures
    actions: [handleTestFailed],
    description: "Alert on test failures",
    priority: "normal",
  });

  // Security Alert: Escalate critical issues
  engine.registerTrigger({
    eventType: "security_alert",
    condition: (data) => data.severity === "critical",
    actions: [handleSecurityAlert],
    description: "Escalate and remediate critical security issues",
    priority: "high",
  });

  // ============================================================================
  // OPERATIONS & COST TRIGGERS
  // ============================================================================

  // Cost Alert: Notify on spending threshold
  engine.registerTrigger({
    eventType: "cost_alert",
    condition: (data) => data.percentOfLimit > 75, // Alert at 75%+
    actions: [handleCostAlert],
    description: "Alert when approaching cost limits",
    priority: "high",
  });

  // Agent Timeout: Auto-recover and retry
  engine.registerTrigger({
    eventType: "agent_timeout",
    actions: [handleAgentTimeout],
    description: "Auto-recover timed-out agents and retry",
    priority: "high",
  });

  // ============================================================================
  // WORKFLOW TRACKING TRIGGERS
  // ============================================================================

  // Workflow Completed: Update metrics and dashboard
  engine.registerTrigger({
    eventType: "workflow_completed",
    actions: [handleWorkflowCompleted],
    description: "Track workflow completion and update metrics",
    priority: "normal",
  });

  // ============================================================================
  // ADVANCED: Custom trigger examples
  // ============================================================================

  // Example: Multi-step deployment workflow
  // When quality gate passes AND specific criteria met
  engine.registerTrigger({
    eventType: "quality_gate_passed",
    condition: (data) => {
      // Only deploy if on main branch
      // (In real implementation, check commit metadata)
      return data.allChecks === true && data.testsPassed === true;
    },
    actions: [
      // Step 1: Run pre-deployment checks
      async (data) => {
        console.log(`Pre-deployment checks for ${data.projectId}...`);
        // TODO: Verify staging environment health
      },

      // Step 2: Create deployment record
      async (data) => {
        console.log(`Creating deployment record for ${data.projectId}...`);
        // TODO: Save deployment info to database
      },

      // Step 3: Trigger actual deployment
      async (data) => {
        console.log(`Triggering deployment of ${data.commitSha}...`);
        // TODO: Call deployment service
      },

      // Step 4: Notify team
      async (data) => {
        console.log(`Notifying team of deployment for ${data.projectId}...`);
        // TODO: Send Slack/email notification
      },
    ],
    description: "Multi-step quality-gate-to-deployment workflow",
    priority: "high",
  });

  // Example: Escalating cost alerts
  // Progressive alerts based on spending level
  engine.registerTrigger({
    eventType: "cost_alert",
    condition: (data) => data.percentOfLimit > 50, // Alert at 50%+
    actions: [
      async (data) => {
        if (data.percentOfLimit < 75) {
          // Low alert: Just log
          console.log(`Cost reaching limits: ${data.percentOfLimit.toFixed(1)}%`);
        } else if (data.percentOfLimit < 90) {
          // Medium alert: Notify
          console.log(`WARNING: Cost at ${data.percentOfLimit.toFixed(1)}%, approaching limit`);
          // TODO: Send warning to team
        } else if (data.percentOfLimit < 100) {
          // High alert: Escalate
          console.log(`CRITICAL: Cost at ${data.percentOfLimit.toFixed(1)}%, enable cost-cutting`);
          // TODO: Enable cost-saving mode
        } else {
          // Critical: Over budget
          console.log(`EMERGENCY: Cost at ${data.percentOfLimit.toFixed(1)}%, STOPPED`);
          // TODO: Halt non-essential operations
        }
      },
    ],
    description: "Graduated cost alert system",
    priority: "high",
  });

  // Example: Build failure recovery
  engine.registerTrigger({
    eventType: "build_completed",
    condition: (data) => data.success === false,
    actions: [
      async (data) => {
        console.log(`Build failed: ${data.buildId}`);
        console.log(`Error: ${data.errorMessage}`);
        // TODO: Post issue to GitHub
        // TODO: Notify team with error details
      },
    ],
    description: "Track and alert on build failures",
    priority: "high",
  });

  // ============================================================================
  // Initialization complete
  // ============================================================================

  const stats = engine.getStats();
  console.log(`✅ Event Trigger System initialized`);
  console.log(`   Total triggers: ${stats.totalTriggers}`);
  console.log(`   Events configured: ${Object.keys(stats.triggersByEvent).length}`);
  console.log(`   Triggers by event: ${JSON.stringify(stats.triggersByEvent, null, 2)}`);
}

// ============================================================================
// Usage Examples - how to emit events from your application
// ============================================================================

export async function exampleQualityGateEvent(): Promise<void> {
  const engine = getTriggerEngine();

  // Emit when quality checks complete
  await engine.emitEvent("quality_gate_passed", {
    projectId: "barber-crm",
    commitSha: "abc123def456789",
    testsPassed: true,
    allChecks: true,
    checkDetails: {
      linting: true,
      testing: true,
      coverage: true,
      security: true,
    },
  });
}

export async function exampleCostAlertEvent(): Promise<void> {
  const engine = getTriggerEngine();

  // Emit when spending exceeds threshold
  await engine.emitEvent("cost_alert", {
    projectId: "expensive-project",
    dailyCost: 35.5,
    monthlyCost: 425.75,
    dailyLimit: 50,
    monthlyLimit: 500,
    percentOfLimit: 85.15,
    alertLevel: "warning",
  });
}

export async function exampleBuildEvent(): Promise<void> {
  const engine = getTriggerEngine();

  // Emit when build starts
  await engine.emitEvent("build_started", {
    buildId: "build-2024-02-17-001",
    projectId: "barber-crm",
    version: "1.2.0",
    triggerSource: "webhook",
  });

  // Simulate build completion
  await new Promise((resolve) => setTimeout(resolve, 1000));

  // Emit when build completes
  await engine.emitEvent("build_completed", {
    buildId: "build-2024-02-17-001",
    projectId: "barber-crm",
    version: "1.2.0",
    success: true,
    duration: 120,
    artifactUrl: "https://s3.example.com/barber-crm-1.2.0.zip",
  });
}

export async function exampleWorkflowEvent(): Promise<void> {
  const engine = getTriggerEngine();

  // Emit when workflow completes
  await engine.emitEvent("workflow_completed", {
    workflowId: "wf-2024-02-17-001",
    projectId: "barber-crm",
    totalCost: 5.25,
    executionTimeMs: 45000,
    agentsUsed: ["pm-agent", "codegen-agent"],
    success: true,
    outputPath: "/output/system-design.md",
  });
}

export async function exampleSecurityAlertEvent(): Promise<void> {
  const engine = getTriggerEngine();

  // Emit when security issue detected
  await engine.emitEvent("security_alert", {
    alertId: "sec-2024-02-17-001",
    severity: "critical",
    title: "SQL Injection in login endpoint",
    description: "Unsanitized user input in database query",
    affectedComponent: "api/auth/login",
    cveId: "CVE-2024-12345",
    remediationSteps: [
      "1. Parameterize all database queries",
      "2. Add input validation on API layer",
      "3. Run security audit tools",
      "4. Deploy security patch",
    ],
  });
}

// ============================================================================
// Running examples (uncomment to test)
// ============================================================================

/*
// Test the initialization
await initializeEventSystem();

// Give a moment for events to process
await new Promise(resolve => setTimeout(resolve, 100));

// Example event emissions
await exampleQualityGateEvent();
await exampleCostAlertEvent();
await exampleBuildEvent();
await exampleWorkflowEvent();
await exampleSecurityAlertEvent();

// Check statistics
const engine = getTriggerEngine();
const stats = engine.getStats();
console.log("Final stats:", stats);
*/
