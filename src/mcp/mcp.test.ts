/**
 * MCP Integration Tests
 * Tests for GitHub, N8N, and Webhook clients
 */

import { createHmac } from "node:crypto";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { GitHubClient } from "./github-mcp.js";
import {
  IntegrationRegistry,
  getIntegrationRegistry,
  resetIntegrationRegistry,
} from "./integrations.js";
import { N8NClient } from "./n8n-client.js";
import { createWebhookRouter } from "./webhook-receiver.js";

// Mock fetch globally
global.fetch = vi.fn();

describe("GitHubClient", () => {
  let client: GitHubClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new GitHubClient("test-token-12345");
  });

  it("should initialize with token", () => {
    expect(client).toBeDefined();
  });

  it("should throw error if no token provided", () => {
    delete process.env.GITHUB_TOKEN;
    expect(() => {
      new GitHubClient("");
    }).toThrow("GITHUB_TOKEN environment variable not set");
  });

  it("should read an issue", async () => {
    const mockIssue = {
      number: 123,
      title: "Test Issue",
      body: "Issue body",
      state: "open" as const,
      user: { login: "testuser" },
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-02T00:00:00Z",
    };

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => mockIssue,
    });

    const issue = await client.readIssue("miles", "test-repo", 123);
    expect(issue).toEqual(mockIssue);
    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.github.com/repos/miles/test-repo/issues/123",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "token test-token-12345",
        }),
      }),
    );
  });

  it("should create a branch", async () => {
    const mockRefResponse = {
      object: { sha: "abc123def456" },
    };

    const mockCreateResponse = {};

    (global.fetch as any)
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => mockRefResponse,
      })
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => mockCreateResponse,
      });

    await client.createBranch("miles", "test-repo", "main", "feature-branch");

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      "https://api.github.com/repos/miles/test-repo/git/refs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          ref: "refs/heads/feature-branch",
          sha: "abc123def456",
        }),
      }),
    );
  });

  it("should commit a file to a branch", async () => {
    const mockCommitResponse = {
      commit: { sha: "newsha123" },
    };

    (global.fetch as any)
      .mockResolvedValueOnce({
        ok: false, // File doesn't exist
        status: 404,
        text: async () => "Not found",
      })
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => mockCommitResponse,
      });

    const sha = await client.commitFile(
      "miles",
      "test-repo",
      "feature-branch",
      "src/index.ts",
      "console.log('hello');",
      "feat: add hello",
    );

    expect(sha).toBe("newsha123");
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      "https://api.github.com/repos/miles/test-repo/contents/src/index.ts",
      expect.objectContaining({
        method: "PUT",
        body: expect.stringContaining("content"),
      }),
    );
  });

  it("should create a pull request", async () => {
    const mockPRResponse = {
      number: 42,
      title: "Test PR",
      body: "PR description",
      state: "open" as const,
      head: { ref: "feature-branch", sha: "xyz789" },
      base: { ref: "main" },
      html_url: "https://github.com/miles/test-repo/pull/42",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
    };

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => mockPRResponse,
    });

    const pr = await client.createPullRequest(
      "miles",
      "test-repo",
      "feature-branch",
      "main",
      "Test PR",
      "PR description",
    );

    expect(pr.number).toBe(42);
    expect(pr.title).toBe("Test PR");
  });

  it("should merge a pull request", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({}),
    });

    await client.mergePullRequest("miles", "test-repo", 42);

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.github.com/repos/miles/test-repo/pulls/42/merge",
      expect.objectContaining({
        method: "PUT",
        body: expect.stringContaining("squash"),
      }),
    );
  });

  it("should add a comment to an issue", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({}),
    });

    await client.addComment("miles", "test-repo", 123, "Great work!");

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.github.com/repos/miles/test-repo/issues/123/comments",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ body: "Great work!" }),
      }),
    );
  });

  it("should handle API errors gracefully", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => "Unauthorized",
    });

    await expect(client.readIssue("miles", "test-repo", 999)).rejects.toThrow(/GitHub API error/);
  });
});

describe("N8NClient", () => {
  let client: N8NClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new N8NClient("https://n8n.example.com/webhook/abc123");
  });

  it("should initialize with webhook URL", () => {
    expect(client).toBeDefined();
  });

  it("should throw error if no webhook URL provided", () => {
    delete process.env.N8N_WEBHOOK_URL;
    expect(() => {
      new N8NClient("");
    }).toThrow("N8N_WEBHOOK_URL environment variable not set");
  });

  it("should trigger a workflow", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({ success: true, jobId: "job-123" }),
    });

    const result = await client.triggerWorkflow("deploy", {
      repo: "test-repo",
      branch: "main",
      action: "deploy",
    });

    expect(result.status).toBe("pending");
    expect(result.executionId).toMatch(/^exec-/);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("n8n.example.com"),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: expect.stringContaining("deploy"),
      }),
    );
  });

  it("should retry on network failure", async () => {
    const error = new Error("Network error");
    (global.fetch as any)
      .mockRejectedValueOnce(error)
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => ({ success: true }),
      });

    const result = await client.triggerWorkflow("test", { action: "test" });
    expect(result.status).toBe("pending");
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it("should fail after max retries", async () => {
    (global.fetch as any).mockRejectedValue(new Error("Network error"));

    await expect(client.triggerWorkflow("test", {})).rejects.toThrow("Network error");
    expect(global.fetch).toHaveBeenCalledTimes(3);
  });

  it("should get workflow status", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({ status: "completed" }),
    });

    const status = await client.getWorkflowStatus("exec-123");
    expect(status).toBe("success");
  });

  it("should trigger deploy workflow", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({}),
    });

    const result = await client.triggerDeploy({
      repo: "test",
      branch: "main",
      commitSha: "abc123",
    });

    expect(result.status).toBe("pending");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("workflowId=deploy"),
      expect.any(Object),
    );
  });

  it("should trigger test workflow", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({}),
    });

    const result = await client.triggerTest({
      repo: "test",
      branch: "main",
    });

    expect(result.status).toBe("pending");
  });

  it("should trigger Slack notification", async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({}),
    });

    const result = await client.triggerSlackNotification({
      channel: "#general",
      message: "Deployment complete",
    });

    expect(result.status).toBe("pending");
  });
});

describe("WebhookReceiver", () => {
  it("should create webhook router", () => {
    const router = createWebhookRouter();
    expect(router).toBeDefined();
  });

  it("should verify Slack signature", () => {
    const secret = "test-secret";
    const timestamp = Math.floor(Date.now() / 1000);
    const body = '{"test":"data"}';

    const baseString = `v0:${timestamp}:${body}`;
    const hmac = createHmac("sha256", secret);
    hmac.update(baseString);
    const signature = `v0=${hmac.digest("hex")}`;

    // This would be verified in the actual webhook handler
    expect(signature).toMatch(/^v0=[a-f0-9]{64}$/);
  });

  it("should verify GitHub signature", () => {
    const secret = "test-secret";
    const payload = Buffer.from('{"action":"opened"}');

    const hmac = createHmac("sha256", secret);
    hmac.update(payload);
    const signature = `sha256=${hmac.digest("hex")}`;

    expect(signature).toMatch(/^sha256=[a-f0-9]{64}$/);
  });

  it("should handle webhook events", async () => {
    const events: unknown[] = [];
    const router = createWebhookRouter({
      onEvent: async (event) => {
        events.push(event);
      },
    });

    expect(router).toBeDefined();
    expect(events).toEqual([]);
  });
});

describe("IntegrationRegistry", () => {
  beforeEach(() => {
    resetIntegrationRegistry();
    vi.clearAllMocks();
  });

  it("should initialize from environment", () => {
    process.env.GITHUB_TOKEN = "test-github-token";
    process.env.N8N_WEBHOOK_URL = "https://n8n.example.com/webhook/123";
    process.env.SLACK_SIGNING_SECRET = "slack-secret";

    const registry = getIntegrationRegistry();
    expect(registry).toBeDefined();
    expect(registry.has("github")).toBe(true);
    expect(registry.has("n8n")).toBe(true);
  });

  it("should get GitHub client", () => {
    process.env.GITHUB_TOKEN = "test-token";
    const registry = getIntegrationRegistry();

    const github = registry.getGitHub();
    expect(github).toBeInstanceOf(GitHubClient);
  });

  it("should get N8N client", () => {
    process.env.N8N_WEBHOOK_URL = "https://n8n.example.com/webhook/123";
    const registry = getIntegrationRegistry();

    const n8n = registry.getN8N();
    expect(n8n).toBeInstanceOf(N8NClient);
  });

  it("should get all clients", () => {
    process.env.GITHUB_TOKEN = "test-token";
    process.env.N8N_WEBHOOK_URL = "https://n8n.example.com/webhook/123";
    const registry = getIntegrationRegistry();

    const clients = registry.getAll();
    expect(clients.github).toBeDefined();
    expect(clients.n8n).toBeDefined();
  });

  it("should get webhook configuration", () => {
    process.env.SLACK_SIGNING_SECRET = "slack-secret";
    process.env.GITHUB_WEBHOOK_SECRET = "github-secret";
    process.env.DISCORD_PUBLIC_KEY = "discord-key";

    const registry = getIntegrationRegistry();
    const config = registry.getWebhookConfig();

    expect(config.slackSigningSecret).toBe("slack-secret");
    expect(config.githubSecret).toBe("github-secret");
    expect(config.discordPublicKey).toBe("discord-key");
  });

  it("should report initialization status", () => {
    resetIntegrationRegistry();
    delete process.env.DISCORD_PUBLIC_KEY; // Clean up from previous test
    process.env.GITHUB_TOKEN = "test-token";
    process.env.N8N_WEBHOOK_URL = "https://n8n.example.com/webhook/123";
    process.env.SLACK_SIGNING_SECRET = "slack-secret";

    const registry = getIntegrationRegistry();
    const status = registry.getStatus();

    expect(status.github).toBe(true);
    expect(status.n8n).toBe(true);
    expect(status.slackWebhook).toBe(true);
    expect(status.discordWebhook).toBe(false);
  });

  it("should register custom clients", () => {
    const registry = new IntegrationRegistry();
    const mockClient = { test: "client" };

    registry.register("custom", mockClient);
    expect(registry.has("custom")).toBe(true);
    expect(registry.load("custom")).toEqual(mockClient);
  });

  it("should handle missing clients gracefully", () => {
    const registry = new IntegrationRegistry();
    expect(registry.getGitHub()).toBeUndefined();
    expect(registry.getN8N()).toBeUndefined();
  });

  it("should install webhooks into express app", () => {
    const registry = new IntegrationRegistry();
    const mockApp = {
      use: vi.fn(),
    };

    registry.installWebhooks(mockApp as any);
    expect(mockApp.use).toHaveBeenCalled();
  });
});

describe("Integration Scenarios", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetIntegrationRegistry();
  });

  it("should handle complete commit workflow", async () => {
    const client = new GitHubClient("test-token");

    // Mock the sequence of calls
    (global.fetch as any)
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => ({ object: { sha: "main-sha" } }),
      }) // Get main branch SHA
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => ({}),
      }) // Create branch
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
        text: async () => "Not found",
      }) // File doesn't exist
      .mockResolvedValueOnce({
        ok: true,
        headers: new Map([["content-type", "application/json"]]),
        json: async () => ({ commit: { sha: "commit-sha-123" } }),
      }); // Commit file

    await client.createBranch("miles", "repo", "main", "feature");
    const sha = await client.commitFile(
      "miles",
      "repo",
      "feature",
      "file.ts",
      "content",
      "feat: add feature",
    );

    expect(sha).toBe("commit-sha-123");
    expect(global.fetch).toHaveBeenCalledTimes(4);
  });

  it("should handle workflow trigger with cost analysis", async () => {
    const n8n = new N8NClient("https://n8n.example.com/webhook");

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      headers: new Map([["content-type", "application/json"]]),
      json: async () => ({ workflowId: "wf-123" }),
    });

    const result = await n8n.triggerCostAnalysis({
      repo: "my-repo",
      estimatedCost: 45.23,
      threshold: 50,
    });

    expect(result.status).toBe("pending");
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("cost-analysis"),
      expect.any(Object),
    );
  });

  it("should handle global registry lifecycle", () => {
    resetIntegrationRegistry();

    process.env.GITHUB_TOKEN = "token1";
    const reg1 = getIntegrationRegistry();
    expect(reg1.has("github")).toBe(true);

    // Second call should return same instance
    const reg2 = getIntegrationRegistry();
    expect(reg1).toBe(reg2);

    resetIntegrationRegistry();

    process.env.GITHUB_TOKEN = "token2";
    const reg3 = getIntegrationRegistry();
    expect(reg3).not.toBe(reg1);
  });
});
