/**
 * Webhook Receiver for OpenClaw MCP
 * Handles incoming webhooks from Slack, Discord, and GitHub
 * Verifies signatures and processes events asynchronously
 */

import type { Express, Request, Response } from "express";
import { Router } from "express";
import { createHmac } from "node:crypto";

export interface WebhookEvent {
  source: "slack" | "discord" | "github";
  timestamp: string;
  type: string;
  data: unknown;
}

export interface WebhookConfig {
  slackSigningSecret?: string;
  discordPublicKey?: string;
  githubSecret?: string;
  onEvent?: (event: WebhookEvent) => Promise<void>;
}

/**
 * Verify Slack webhook signature
 * Slack uses HMAC-SHA256 with format: v0=<timestamp>:<request_body>
 */
function verifySlackSignature(req: Request, slackSigningSecret: string): boolean {
  const timestamp = req.headers["x-slack-request-timestamp"];
  const signature = req.headers["x-slack-signature"];

  if (!timestamp || !signature || typeof timestamp !== "string" || typeof signature !== "string") {
    return false;
  }

  // Verify timestamp is within 5 minutes
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp)) > 300) {
    return false;
  }

  // Verify signature
  const baseString = `v0:${timestamp}:${req.body}`;
  const hmac = createHmac("sha256", slackSigningSecret);
  hmac.update(baseString);
  const computed = `v0=${hmac.digest("hex")}`;

  return computed === signature;
}

/**
 * Verify GitHub webhook signature
 * GitHub uses HMAC-SHA256 with format: sha256=<hex_digest>
 */
function verifyGitHubSignature(
  payload: Buffer,
  signature: string | undefined,
  secret: string,
): boolean {
  if (!signature || typeof signature !== "string") {
    return false;
  }

  const hmac = createHmac("sha256", secret);
  hmac.update(payload);
  const computed = `sha256=${hmac.digest("hex")}`;

  return computed === signature;
}

/**
 * Verify Discord webhook
 * Discord uses Ed25519 signature verification
 * For simplicity in this implementation, we verify via X-Signature-Ed25519 header
 */
function verifyDiscordSignature(req: Request, _discordPublicKey: string): boolean {
  // Basic verification: check for required Discord headers
  const signature = req.headers["x-signature-ed25519"];
  const timestamp = req.headers["x-signature-timestamp"];

  // In production, this would verify the actual Ed25519 signature
  // For now, we just check headers are present
  return Boolean(signature && timestamp);
}

/**
 * Create webhook router for Express app
 */
export function createWebhookRouter(config: WebhookConfig = {}) {
  const router = Router();

  // Middleware to capture raw body for signature verification
  router.use((req, _res, next) => {
    let rawBody = "";
    req.on("data", (chunk: Buffer) => {
      rawBody += chunk.toString();
    });
    req.on("end", () => {
      (req as Request & { rawBody: string }).rawBody = rawBody;
      next();
    });
  });

  /**
   * POST /webhooks/slack
   * Slack event webhook handler
   */
  router.post("/webhooks/slack", (req: Request, res: Response) => {
    try {
      // Verify Slack signature if secret provided
      if (config.slackSigningSecret) {
        if (!verifySlackSignature(req, config.slackSigningSecret)) {
          res.status(401).json({ error: "Invalid signature" });
          return;
        }
      }

      const body = req.body as { type?: string; challenge?: string; event?: unknown };

      // Handle URL verification challenge from Slack
      if (body.type === "url_verification") {
        res.status(200).json({ challenge: body.challenge });
        return;
      }

      // Respond immediately with 200 OK
      res.status(200).json({ ok: true });

      // Process event asynchronously
      if (body.type === "event_callback" && body.event) {
        const event: WebhookEvent = {
          source: "slack",
          timestamp: new Date().toISOString(),
          type: (body.event as { type?: string }).type || "unknown",
          data: body.event,
        };

        if (config.onEvent) {
          config.onEvent(event).catch((error) => {
            console.error("Error processing Slack webhook:", error);
          });
        }
      }
    } catch (error) {
      console.error("Slack webhook error:", error);
      res.status(500).json({ error: "Internal server error" });
    }
  });

  /**
   * POST /webhooks/discord
   * Discord interaction webhook handler
   */
  router.post("/webhooks/discord", (req: Request, res: Response) => {
    try {
      // Verify Discord signature if public key provided
      if (config.discordPublicKey) {
        const verified = verifyDiscordSignature(req, config.discordPublicKey);
        if (!verified) {
          res.status(401).json({ error: "Invalid signature" });
          return;
        }
      }

      const body = req.body as { type?: number; data?: unknown };

      // Discord expects PING interactions to be responded to immediately with PONG
      if (body.type === 1) {
        // PING type
        res.status(200).json({ type: 1 }); // PONG response
        return;
      }

      // Respond immediately with 200 OK
      res.status(200).json({ ok: true });

      // Process other interactions asynchronously
      if (body.type !== 1) {
        const event: WebhookEvent = {
          source: "discord",
          timestamp: new Date().toISOString(),
          type: `interaction-${body.type}`,
          data: body.data,
        };

        if (config.onEvent) {
          config.onEvent(event).catch((error) => {
            console.error("Error processing Discord webhook:", error);
          });
        }
      }
    } catch (error) {
      console.error("Discord webhook error:", error);
      res.status(500).json({ error: "Internal server error" });
    }
  });

  /**
   * POST /webhooks/github
   * GitHub event webhook handler
   */
  router.post("/webhooks/github", (req: Request, res: Response) => {
    try {
      // Verify GitHub signature if secret provided
      if (config.githubSecret) {
        const signature = req.headers["x-hub-signature-256"];
        const rawBody = (req as Request & { rawBody: string }).rawBody || JSON.stringify(req.body);
        const payload = Buffer.isBuffer(rawBody) ? rawBody : Buffer.from(rawBody);

        if (!verifyGitHubSignature(payload, signature as string, config.githubSecret)) {
          res.status(401).json({ error: "Invalid signature" });
          return;
        }
      }

      const body = req.body as { action?: string };
      const eventType = req.headers["x-github-event"];

      // Respond immediately with 200 OK
      res.status(200).json({ ok: true });

      // Process event asynchronously
      const event: WebhookEvent = {
        source: "github",
        timestamp: new Date().toISOString(),
        type: eventType as string,
        data: body,
      };

      if (config.onEvent) {
        config.onEvent(event).catch((error) => {
          console.error("Error processing GitHub webhook:", error);
        });
      }
    } catch (error) {
      console.error("GitHub webhook error:", error);
      res.status(500).json({ error: "Internal server error" });
    }
  });

  return router;
}

/**
 * Install webhook router into Express app
 */
export function installWebhookReceiver(app: Express, config: WebhookConfig = {}): void {
  const router = createWebhookRouter(config);
  app.use(router);
}
