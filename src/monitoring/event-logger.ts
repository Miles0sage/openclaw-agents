/**
 * Event Logger
 * Structured logging to JSON with file persistence and rotation
 */

import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { Event } from "./types.js";

const EVENTS_FILE = "/tmp/events.json";
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const ARCHIVE_DIR = "/tmp/events_archive";

export class EventLogger {
  private initialized = false;

  async init(): Promise<void> {
    if (this.initialized) return;

    try {
      // Ensure archive directory exists
      await fs.mkdir(ARCHIVE_DIR, { recursive: true });

      // Create events file if it doesn't exist
      try {
        await fs.access(EVENTS_FILE);
      } catch {
        await fs.writeFile(EVENTS_FILE, "[]");
      }

      this.initialized = true;
    } catch (err) {
      console.error("Failed to initialize EventLogger:", err);
    }
  }

  async logEvent(
    type: string,
    data: Record<string, unknown>,
    options?: {
      agentId?: string;
      taskId?: string;
      projectId?: string;
      level?: "debug" | "info" | "warn" | "error";
    },
  ): Promise<void> {
    await this.init();

    const event: Event = {
      timestamp: new Date().toISOString(),
      type,
      agent_id: options?.agentId,
      task_id: options?.taskId,
      project_id: options?.projectId,
      level: options?.level || "info",
      message: String(data.message || type),
      data,
    };

    try {
      // Check file size and rotate if needed
      await this.checkAndRotate();

      // Append event to file
      const events = await this.readEvents();
      events.push(event);

      // Keep only last 10000 events in memory to avoid huge arrays
      const eventsToWrite = events.slice(-10000);
      await fs.writeFile(EVENTS_FILE, JSON.stringify(eventsToWrite, null, 0));
    } catch (err) {
      console.error("Failed to log event:", err);
    }
  }

  async getEvents(filter?: {
    type?: string;
    startTime?: Date;
    endTime?: Date;
    level?: string;
  }): Promise<Event[]> {
    await this.init();

    try {
      const events = await this.readEvents();

      return events.filter((event) => {
        if (filter?.type && event.type !== filter.type) return false;
        if (filter?.level && event.level !== filter.level) return false;

        if (filter?.startTime) {
          const eventTime = new Date(event.timestamp).getTime();
          const startTime = filter.startTime.getTime();
          if (eventTime < startTime) return false;
        }

        if (filter?.endTime) {
          const eventTime = new Date(event.timestamp).getTime();
          const endTime = filter.endTime.getTime();
          if (eventTime > endTime) return false;
        }

        return true;
      });
    } catch (err) {
      console.error("Failed to get events:", err);
      return [];
    }
  }

  async clearOld(olderThanSeconds: number): Promise<void> {
    await this.init();

    try {
      const cutoffTime = new Date(Date.now() - olderThanSeconds * 1000);
      const events = await this.readEvents();

      const newEvents = events.filter((event) => new Date(event.timestamp) > cutoffTime);

      await fs.writeFile(EVENTS_FILE, JSON.stringify(newEvents, null, 0));
    } catch (err) {
      console.error("Failed to clear old events:", err);
    }
  }

  private async checkAndRotate(): Promise<void> {
    try {
      const stats = await fs.stat(EVENTS_FILE);

      if (stats.size > MAX_FILE_SIZE) {
        const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
        const archiveName = `events-${timestamp}.json`;
        const archivePath = path.join(ARCHIVE_DIR, archiveName);

        await fs.rename(EVENTS_FILE, archivePath);
        await fs.writeFile(EVENTS_FILE, "[]");

        console.log(`Events file rotated to ${archivePath}`);
      }
    } catch (err) {
      console.error("Failed to rotate events file:", err);
    }
  }

  private async readEvents(): Promise<Event[]> {
    try {
      const content = await fs.readFile(EVENTS_FILE, "utf-8");
      return JSON.parse(content) || [];
    } catch {
      return [];
    }
  }
}

export const eventLogger = new EventLogger();
