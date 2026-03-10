/**
 * Integration Registry for OpenClaw MCP
 * Manages initialization and access to all external service clients
 * Auto-loads from environment variables
 */

import type { Express } from "express";
import type { WebhookConfig } from "./webhook-receiver.js";
import { GitHubClient } from "./github-mcp.js";
import { N8NClient } from "./n8n-client.js";
import { createWebhookRouter } from "./webhook-receiver.js";

export interface IntegrationClients {
  github?: GitHubClient;
  n8n?: N8NClient;
}

export class IntegrationRegistry {
  private clients: Map<string, unknown> = new Map();
  private config: Map<string, unknown> = new Map();

  /**
   * Initialize registry from environment variables
   */
  initialize(): void {
    // GitHub client
    const githubToken = process.env.GITHUB_TOKEN;
    if (githubToken) {
      try {
        this.clients.set("github", new GitHubClient(githubToken));
        this.config.set("github.token", githubToken);
      } catch (error) {
        console.error("Failed to initialize GitHub client:", error);
      }
    }

    // N8N client
    const n8nUrl = process.env.N8N_WEBHOOK_URL;
    if (n8nUrl) {
      try {
        this.clients.set("n8n", new N8NClient(n8nUrl));
        this.config.set("n8n.webhook_url", n8nUrl);
      } catch (error) {
        console.error("Failed to initialize N8N client:", error);
      }
    }

    // Webhook secrets
    const slackSecret = process.env.SLACK_SIGNING_SECRET;
    if (slackSecret) {
      this.config.set("slack.signing_secret", slackSecret);
    }

    const discordPublicKey = process.env.DISCORD_PUBLIC_KEY;
    if (discordPublicKey) {
      this.config.set("discord.public_key", discordPublicKey);
    }

    const githubSecret = process.env.GITHUB_WEBHOOK_SECRET;
    if (githubSecret) {
      this.config.set("github.webhook_secret", githubSecret);
    }
  }

  /**
   * Register a client manually
   */
  register(name: string, client: unknown): void {
    this.clients.set(name, client);
  }

  /**
   * Get a registered client
   */
  load<T>(name: string): T | undefined {
    return this.clients.get(name) as T | undefined;
  }

  /**
   * Get all registered clients
   */
  getAll(): IntegrationClients {
    return {
      github: this.clients.get("github") as GitHubClient | undefined,
      n8n: this.clients.get("n8n") as N8NClient | undefined,
    };
  }

  /**
   * Get GitHub client
   */
  getGitHub(): GitHubClient | undefined {
    return this.clients.get("github") as GitHubClient | undefined;
  }

  /**
   * Get N8N client
   */
  getN8N(): N8NClient | undefined {
    return this.clients.get("n8n") as N8NClient | undefined;
  }

  /**
   * Get webhook configuration
   */
  getWebhookConfig(): WebhookConfig {
    return {
      slackSigningSecret: this.config.get("slack.signing_secret") as string | undefined,
      discordPublicKey: this.config.get("discord.public_key") as string | undefined,
      githubSecret: this.config.get("github.webhook_secret") as string | undefined,
    };
  }

  /**
   * Install webhooks into express app
   */
  installWebhooks(app: Express, onEvent?: (event: unknown) => Promise<void>): void {
    const config = this.getWebhookConfig();
    if (onEvent) {
      config.onEvent = onEvent;
    }
    const router = createWebhookRouter(config);
    app.use(router);
  }

  /**
   * Check if client is available
   */
  has(name: string): boolean {
    return this.clients.has(name);
  }

  /**
   * Get initialization status
   */
  getStatus(): {
    github: boolean;
    n8n: boolean;
    slackWebhook: boolean;
    discordWebhook: boolean;
    githubWebhook: boolean;
  } {
    return {
      github: this.clients.has("github"),
      n8n: this.clients.has("n8n"),
      slackWebhook: this.config.has("slack.signing_secret"),
      discordWebhook: this.config.has("discord.public_key"),
      githubWebhook: this.config.has("github.webhook_secret"),
    };
  }
}

/**
 * Global integration registry instance
 */
let globalRegistry: IntegrationRegistry | null = null;

/**
 * Get or create global registry
 */
export function getIntegrationRegistry(): IntegrationRegistry {
  if (!globalRegistry) {
    globalRegistry = new IntegrationRegistry();
    globalRegistry.initialize();
  }
  return globalRegistry;
}

/**
 * Reset global registry (for testing)
 */
export function resetIntegrationRegistry(): void {
  globalRegistry = null;
}
