import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { createAgencyHttpHandler } from "./agency-http.js";
import type { AgencyConfig } from "./agency.types.js";

const TEST_TOKEN = "test-agency-token";

function fixtureAgencyConfig(): AgencyConfig {
  return {
    projects: [
      {
        id: "p1",
        name: "Project One",
        repo: "org/project-one",
        local_path: "/tmp/project-one",
        github_url: "https://github.com/org/project-one",
        branch: "main",
        language: "typescript",
        test_command: "npm test",
      },
    ],
    agency: {
      name: "Test Agency",
      owner: "tester",
      timezone: "UTC",
    },
    cycle: {
      frequency: "every 4 hours",
      cron: "0 */4 * * *",
      max_parallel_agents: 1,
      timeout_minutes: 45,
    },
    costs: {
      per_cycle_hard_cap: 8,
      per_cycle_typical: 3.8,
      per_project_cap: 2,
      daily_hard_cap: 40,
      monthly_hard_cap: 600,
      monthly_soft_cap: 400,
    },
    model_selection: {
      planning: "claude-opus-4-6",
      execution: "claude-haiku-4-5-20251001",
      review: "claude-opus-4-6",
    },
  };
}

async function startAgencyServer(): Promise<{
  baseUrl: string;
  close: () => Promise<void>;
}> {
  const handler = createAgencyHttpHandler();
  const server = createServer((req, res) => {
    void (async () => {
      try {
        const handled = await handler(req, res);
        if (!handled) {
          res.statusCode = 404;
          res.end("Not Found");
        }
      } catch (err) {
        res.statusCode = 500;
        res.end(String(err));
      }
    })();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const address = server.address() as AddressInfo;
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    close: async () => {
      await new Promise<void>((resolve, reject) => {
        server.close((err) => {
          if (err) reject(err);
          else resolve();
        });
      });
    },
  };
}

describe("agency http", () => {
  let tempDir = "";
  let configPath = "";
  let prevAgencyConfigPath: string | undefined;
  let prevGatewayToken: string | undefined;
  let prevSlackWebhookUrl: string | undefined;

  beforeEach(async () => {
    tempDir = await mkdtemp(path.join(os.tmpdir(), "agency-http-test-"));
    configPath = path.join(tempDir, "agency-config.json");
    await writeFile(configPath, JSON.stringify(fixtureAgencyConfig(), null, 2), "utf-8");

    prevAgencyConfigPath = process.env.AGENCY_CONFIG_PATH;
    prevGatewayToken = process.env.MOLTBOT_GATEWAY_TOKEN;
    prevSlackWebhookUrl = process.env.SLACK_WEBHOOK_URL;

    process.env.AGENCY_CONFIG_PATH = configPath;
    process.env.MOLTBOT_GATEWAY_TOKEN = TEST_TOKEN;
    delete process.env.SLACK_WEBHOOK_URL;
  });

  afterEach(async () => {
    if (prevAgencyConfigPath === undefined) {
      delete process.env.AGENCY_CONFIG_PATH;
    } else {
      process.env.AGENCY_CONFIG_PATH = prevAgencyConfigPath;
    }
    if (prevGatewayToken === undefined) {
      delete process.env.MOLTBOT_GATEWAY_TOKEN;
    } else {
      process.env.MOLTBOT_GATEWAY_TOKEN = prevGatewayToken;
    }
    if (prevSlackWebhookUrl === undefined) {
      delete process.env.SLACK_WEBHOOK_URL;
    } else {
      process.env.SLACK_WEBHOOK_URL = prevSlackWebhookUrl;
    }

    if (tempDir) {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  test("rejects unauthorized agency requests", async () => {
    const server = await startAgencyServer();
    try {
      const res = await fetch(`${server.baseUrl}/api/agency/config`);
      expect(res.status).toBe(401);
      const json = (await res.json()) as { code?: string };
      expect(json.code).toBe("AUTH_FAILED");
    } finally {
      await server.close();
    }
  });

  test("supports GET /api/agency/config", async () => {
    const server = await startAgencyServer();
    try {
      const res = await fetch(`${server.baseUrl}/api/agency/config`, {
        headers: { authorization: `Bearer ${TEST_TOKEN}` },
      });
      expect(res.status).toBe(200);
      const json = (await res.json()) as {
        config?: AgencyConfig;
        config_file?: string;
      };
      expect(json.config_file).toBe(configPath);
      expect(json.config?.agency.name).toBe("Test Agency");
    } finally {
      await server.close();
    }
  });

  test("persists PUT /api/agency/config updates to agency-config.json", async () => {
    const server = await startAgencyServer();
    try {
      const putRes = await fetch(`${server.baseUrl}/api/agency/config`, {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${TEST_TOKEN}`,
        },
        body: JSON.stringify({
          updates: {
            costs: {
              per_cycle_hard_cap: 12,
            },
          },
        }),
      });
      expect(putRes.status).toBe(200);

      const raw = await readFile(configPath, "utf-8");
      const updated = JSON.parse(raw) as AgencyConfig;
      expect(updated.costs.per_cycle_hard_cap).toBe(12);
    } finally {
      await server.close();
    }
  });

  test("returns 405 for unsupported config method", async () => {
    const server = await startAgencyServer();
    try {
      const res = await fetch(`${server.baseUrl}/api/agency/config`, {
        method: "POST",
        headers: { authorization: `Bearer ${TEST_TOKEN}` },
      });
      expect(res.status).toBe(405);
      const json = (await res.json()) as { code?: string };
      expect(json.code).toBe("METHOD_NOT_ALLOWED");
    } finally {
      await server.close();
    }
  });
});
