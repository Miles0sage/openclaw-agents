import type { IncomingMessage, ServerResponse } from "node:http";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  handleTelegramHttpRequest,
  normalizeTelegramWebhookPath,
  registerTelegramHttpHandler,
  clearTelegramHttpRoutes,
} from "./registry.js";

describe("Telegram HTTP handler", () => {
  beforeEach(() => {
    clearTelegramHttpRoutes();
  });
  it("normalizes webhook paths", () => {
    expect(normalizeTelegramWebhookPath()).toBe("/telegram/webhook");
    expect(normalizeTelegramWebhookPath("/custom")).toBe("/custom");
    expect(normalizeTelegramWebhookPath("custom")).toBe("/custom");
    expect(normalizeTelegramWebhookPath("/tg/hook")).toBe("/tg/hook");
  });

  it("registers and handles telegram webhook requests", async () => {
    const mockHandler = vi.fn();
    const req = {
      url: "/telegram/webhook",
      headers: {},
    } as unknown as IncomingMessage;
    const res = {} as unknown as ServerResponse;

    registerTelegramHttpHandler({
      path: "/telegram/webhook",
      token: "test-token",
      handler: mockHandler,
    });

    const handled = await handleTelegramHttpRequest(req, res);

    expect(handled).toBe(true);
    expect(mockHandler).toHaveBeenCalledWith(req, res);
  });

  it("rejects requests without matching path", async () => {
    const req = {
      url: "/unknown",
      headers: {},
    } as unknown as IncomingMessage;
    const res = {} as unknown as ServerResponse;

    const handled = await handleTelegramHttpRequest(req, res);

    expect(handled).toBe(false);
  });

  it("verifies telegram secret token", async () => {
    const mockHandler = vi.fn();
    const mockRes = {
      writeHead: vi.fn(),
      end: vi.fn(),
    } as unknown as ServerResponse;

    registerTelegramHttpHandler({
      path: "/telegram/webhook",
      token: "test-token",
      secret: "super-secret-123",
      handler: mockHandler,
    });

    const req = {
      url: "/telegram/webhook",
      headers: {
        "x-telegram-bot-api-secret-token": "wrong-secret",
      },
    } as unknown as IncomingMessage;

    const handled = await handleTelegramHttpRequest(req, mockRes);

    expect(handled).toBe(true);
    expect(mockHandler).not.toHaveBeenCalled();
    expect(mockRes.writeHead).toHaveBeenCalledWith(403, {
      "Content-Type": "application/json",
    });
  });

  it("accepts correct telegram secret token", async () => {
    const mockHandler = vi.fn();
    registerTelegramHttpHandler({
      path: "/telegram/webhook",
      token: "test-token",
      secret: "super-secret-123",
      handler: mockHandler,
    });

    const req = {
      url: "/telegram/webhook",
      headers: {
        "x-telegram-bot-api-secret-token": "super-secret-123",
      },
    } as unknown as IncomingMessage;
    const res = {} as unknown as ServerResponse;

    const handled = await handleTelegramHttpRequest(req, res);

    expect(handled).toBe(true);
    expect(mockHandler).toHaveBeenCalledWith(req, res);
  });
});
