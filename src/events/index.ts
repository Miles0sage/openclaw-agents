/**
 * Event Trigger System - Index and Exports
 * Central export point for event-driven automation system
 */

export {
  TriggerEngine,
  getTriggerEngine,
  resetTriggerEngine,
  type EventTrigger,
} from "./trigger-engine.js";

export {
  handleQualityGatePassed,
  handleTestFailed,
  handleCostAlert,
  handleAgentTimeout,
  handleWorkflowCompleted,
  handleBuildStarted,
  handleBuildCompleted,
  handleDeploymentStarted,
  handleSecurityAlert,
  type QualityGatePassedData,
  type TestFailedData,
  type CostAlertData,
  type AgentTimeoutData,
  type WorkflowCompletedData,
  type BuildStartedData,
  type BuildCompletedData,
  type DeploymentStartedData,
  type SecurityAlertData,
} from "./event-handlers.js";
