/**
 * MCP (Model Context Protocol) Integration Module
 * Provides integration with external services: GitHub, N8N, and webhook receivers
 */

export { GitHubClient } from "./github-mcp.js";
export type {
  GitHubIssue,
  GitHubPR,
  GitHubCommit,
  GitHubBranch,
  CommitResponse,
  FileContent,
} from "./github-mcp.js";

export { N8NClient } from "./n8n-client.js";
export type { WorkflowPayload, WorkflowRun } from "./n8n-client.js";

export { createWebhookRouter, installWebhookReceiver } from "./webhook-receiver.js";
export type { WebhookEvent, WebhookConfig } from "./webhook-receiver.js";

export {
  IntegrationRegistry,
  getIntegrationRegistry,
  resetIntegrationRegistry,
} from "./integrations.js";
export type { IntegrationClients } from "./integrations.js";
