/**
 * Alert Manager
 * Create, store, and send alerts to Telegram and Slack
 */

import * as fs from "node:fs/promises";
import type { Alert } from "./types.js";

const ALERTS_FILE = "/tmp/alerts.json";
const ALERT_AUTO_ACK_TIME = 24 * 60 * 60 * 1000; // 24 hours

export class AlertManager {
  private initialized = false;
  private telegramBotToken?: string;
  private telegramUserId?: string;
  private slackWebhookUrl?: string;

  constructor(options?: {
    telegramBotToken?: string;
    telegramUserId?: string;
    slackWebhookUrl?: string;
  }) {
    this.telegramBotToken = options?.telegramBotToken || process.env.TELEGRAM_BOT_TOKEN;
    this.telegramUserId = options?.telegramUserId || process.env.TELEGRAM_USER_ID;
    this.slackWebhookUrl = options?.slackWebhookUrl || process.env.SLACK_WEBHOOK_URL;
  }

  async init(): Promise<void> {
    if (this.initialized) return;

    try {
      // Create alerts file if it doesn't exist
      try {
        await fs.access(ALERTS_FILE);
      } catch {
        await fs.writeFile(ALERTS_FILE, JSON.stringify([]));
      }

      this.initialized = true;
    } catch (err) {
      console.error("Failed to initialize AlertManager:", err);
    }
  }

  async createAlert(
    type: "error" | "warning" | "success" | "info",
    message: string,
    context?: Record<string, unknown>,
  ): Promise<Alert> {
    await this.init();

    const alert: Alert = {
      id: `alert-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      type,
      timestamp: new Date().toISOString(),
      message,
      context,
      acknowledged: false,
    };

    try {
      // Save alert
      await this.saveAlert(alert);

      // Send alert to channels (async, don't wait)
      this.sendAlert(alert).catch((err) => console.error("Failed to send alert:", err));

      return alert;
    } catch (err) {
      console.error("Failed to create alert:", err);
      return alert;
    }
  }

  async sendAlert(alert: Alert): Promise<void> {
    // Send to Telegram
    if (this.telegramBotToken && this.telegramUserId) {
      try {
        await this.sendTelegramAlert(alert);
      } catch (err) {
        console.error("Failed to send Telegram alert:", err);
      }
    }

    // Send to Slack
    if (this.slackWebhookUrl) {
      try {
        await this.sendSlackAlert(alert);
      } catch (err) {
        console.error("Failed to send Slack alert:", err);
      }
    }
  }

  async getAlerts(filter?: { acknowledged?: boolean; type?: string }): Promise<Alert[]> {
    await this.init();

    try {
      const alerts = await this.readAlerts();

      // Auto-acknowledge alerts older than 24 hours
      const now = Date.now();
      for (const alert of alerts) {
        if (
          !alert.acknowledged &&
          now - new Date(alert.timestamp).getTime() > ALERT_AUTO_ACK_TIME
        ) {
          alert.acknowledged = true;
          alert.acknowledged_at = new Date().toISOString();
        }
      }

      // Save updated alerts
      await fs.writeFile(ALERTS_FILE, JSON.stringify(alerts, null, 0));

      // Filter by criteria
      return alerts.filter((alert) => {
        if (filter?.acknowledged !== undefined && alert.acknowledged !== filter.acknowledged)
          return false;
        if (filter?.type && alert.type !== filter.type) return false;
        return true;
      });
    } catch (err) {
      console.error("Failed to get alerts:", err);
      return [];
    }
  }

  async acknowledgeAlert(alertId: string): Promise<void> {
    await this.init();

    try {
      const alerts = await this.readAlerts();
      const alert = alerts.find((a) => a.id === alertId);

      if (alert) {
        alert.acknowledged = true;
        alert.acknowledged_at = new Date().toISOString();
        await fs.writeFile(ALERTS_FILE, JSON.stringify(alerts, null, 0));
      }
    } catch (err) {
      console.error("Failed to acknowledge alert:", err);
    }
  }

  async clearOld(olderThanSeconds: number): Promise<void> {
    await this.init();

    try {
      const cutoffTime = new Date(Date.now() - olderThanSeconds * 1000);
      const alerts = await this.readAlerts();

      // Keep alerts acknowledged before cutoff time
      const newAlerts = alerts.filter((alert) => {
        if (!alert.acknowledged) return true;
        if (!alert.acknowledged_at) return true;
        return new Date(alert.acknowledged_at) > cutoffTime;
      });

      await fs.writeFile(ALERTS_FILE, JSON.stringify(newAlerts, null, 0));
    } catch (err) {
      console.error("Failed to clear old alerts:", err);
    }
  }

  private async sendTelegramAlert(alert: Alert): Promise<void> {
    const botToken = this.telegramBotToken;
    const userId = this.telegramUserId;

    if (!botToken || !userId) return;

    const text = this.formatTelegramMessage(alert);
    const url = `https://api.telegram.org/bot${botToken}/sendMessage`;

    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: userId,
        text,
        parse_mode: "HTML",
      }),
    });

    if (!response.ok) {
      throw new Error(`Telegram API error: ${response.status}`);
    }
  }

  private async sendSlackAlert(alert: Alert): Promise<void> {
    const webhookUrl = this.slackWebhookUrl;
    if (!webhookUrl) return;

    const color = this.getSlackColor(alert.type);
    const payload = {
      attachments: [
        {
          color,
          title: `${alert.type.toUpperCase()}: ${alert.message}`,
          text: alert.context ? JSON.stringify(alert.context, null, 2) : "",
          footer: "OpenClaw Monitoring",
          ts: Math.floor(new Date(alert.timestamp).getTime() / 1000),
        },
      ],
    };

    const response = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Slack API error: ${response.status}`);
    }
  }

  private formatTelegramMessage(alert: Alert): string {
    const emoji = this.getEmoji(alert.type);
    const title = `<b>${emoji} ${alert.type.toUpperCase()}</b>\n\n`;
    const message = `<code>${alert.message}</code>\n`;
    const context = alert.context ? `\n<pre>${JSON.stringify(alert.context, null, 2)}</pre>` : "";

    return title + message + context;
  }

  private getSlackColor(type: string): string {
    switch (type) {
      case "error":
        return "#FF0000";
      case "warning":
        return "#FFA500";
      case "success":
        return "#00AA00";
      case "info":
        return "#0099FF";
      default:
        return "#999999";
    }
  }

  private getEmoji(type: string): string {
    switch (type) {
      case "error":
        return "❌";
      case "warning":
        return "⚠️";
      case "success":
        return "✅";
      case "info":
        return "ℹ️";
      default:
        return "📌";
    }
  }

  private async saveAlert(alert: Alert): Promise<void> {
    try {
      const alerts = await this.readAlerts();
      alerts.push(alert);

      // Keep only last 1000 alerts
      const alertsToWrite = alerts.slice(-1000);
      await fs.writeFile(ALERTS_FILE, JSON.stringify(alertsToWrite, null, 0));
    } catch (err) {
      console.error("Failed to save alert:", err);
    }
  }

  private async readAlerts(): Promise<Alert[]> {
    try {
      const content = await fs.readFile(ALERTS_FILE, "utf-8");
      return JSON.parse(content) || [];
    } catch {
      return [];
    }
  }
}

export const alertManager = new AlertManager();
