/**
 * OpenClaw Personal Assistant — Cloudflare Worker
 *
 * Hono-based edge proxy that sits in front of the VPS gateway
 * (https://<your-domain>).  Adds bearer-token auth, KV-backed
 * session persistence, rate limiting, a /api/status dashboard
 * endpoint that aggregates all gateway subsystems into one payload,
 * WebSocket proxy at /ws, and a landing page chat UI.
 *
 * Gateway APIs proxied:
 *   POST /api/chat               — conversational gateway (session memory)
 *   POST /api/proposal/create    — create a proposal
 *   GET  /api/proposals           — list proposals
 *   GET  /api/proposal/:id        — get single proposal
 *   GET  /api/jobs                — list jobs
 *   POST /api/job/create          — create a job
 *   GET  /api/job/:id             — get single job
 *   POST /api/job/:id/approve     — approve a job
 *   GET  /api/events              — system events
 *   GET  /api/memories            — memory search
 *   POST /api/memory/add          — add a memory
 *   GET  /api/cron/jobs           — cron status
 *   GET  /api/costs/summary       — budget / cost summary
 *   GET  /api/policy              — ops policy
 *   GET  /api/quotas/status       — quota status
 *   POST /api/route               — intelligent routing
 *   GET  /api/route/models        — available models
 *   GET  /api/route/health        — router health
 *   GET  /api/heartbeat/status    — agent heartbeat
 *   GET  /api/agents              — registered agents
 *   WS   /ws                      — real-time WebSocket proxy
 */

import { Hono } from "hono";
import { cors } from "hono/cors";
import * as Memory from "./memory";
import { extractAndStore, getMemoryContext } from "./extraction";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Env {
  GATEWAY_URL: string;
  GATEWAY_TOKEN: string;
  BEARER_TOKEN?: string; // optional extra auth for this worker
  ENVIRONMENT: string;
  RATE_LIMIT_PER_MINUTE: string;
  GEMINI_API_KEY: string;
  GEMINI_MODEL: string;
  DEEPSEEK_API_KEY: string;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_OWNER_ID: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  DB: D1Database;
  KV_CACHE: KVNamespace;
  KV_SESSIONS: KVNamespace;
}

interface ChatRequest {
  message: string;
  sessionKey?: string;
  agent?: string;
  model?: string;
}

interface SessionData {
  messages: Array<{ role: string; content: string; timestamp: string }>;
  created: string;
  updated: string;
  messageCount: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Forward a request to the VPS gateway, returning the parsed JSON. */
async function gatewayFetch(env: Env, path: string, options: RequestInit = {}): Promise<Response> {
  const url = `${env.GATEWAY_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Auth-Token": env.GATEWAY_TOKEN,
    ...(options.headers as Record<string, string> | undefined),
  };

  try {
    const resp = await fetch(url, { ...options, headers });
    return resp;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return new Response(JSON.stringify({ error: "gateway_unreachable", detail: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

/**
 * Simple in-memory rate limiter keyed by IP (resets per isolate).
 * The `internal` flag allows exempting server-side calls (e.g. /api/status
 * fan-out) from being counted against user limits.
 */
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + 60_000 });
    return true;
  }
  entry.count++;
  return entry.count <= maxPerMinute;
}

// Paths that are exempt from auth and rate limiting
const PUBLIC_PATHS = new Set(["/", "/health", "/ws", "/webhook/telegram"]);

// ---------------------------------------------------------------------------
// Gemini → OpenAI tool format converter
// ---------------------------------------------------------------------------

interface OpenAITool {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

/** Convert Gemini `type: "STRING"` schema to JSON Schema `type: "string"` */
function convertGeminiSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const typeMap: Record<string, string> = {
    STRING: "string",
    NUMBER: "number",
    INTEGER: "integer",
    BOOLEAN: "boolean",
    ARRAY: "array",
    OBJECT: "object",
  };
  const result: Record<string, unknown> = {};
  if (schema.type)
    result.type = typeMap[schema.type as string] || (schema.type as string).toLowerCase();
  if (schema.description) result.description = schema.description;
  if (schema.required) result.required = schema.required;
  if (schema.items) result.items = convertGeminiSchema(schema.items as Record<string, unknown>);
  if (schema.properties) {
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(schema.properties as Record<string, unknown>)) {
      props[k] = convertGeminiSchema(v as Record<string, unknown>);
    }
    result.properties = props;
  }
  return result;
}

/** Convert OPENCLAW_TOOLS (Gemini format) to OpenAI tools format at runtime */
function convertToolsToOpenAI(geminiTools: Array<Record<string, unknown>>): OpenAITool[] {
  const tools: OpenAITool[] = [];
  for (const group of geminiTools) {
    const decls = group.functionDeclarations as Array<Record<string, unknown>> | undefined;
    if (!decls) continue;
    for (const decl of decls) {
      tools.push({
        type: "function",
        function: {
          name: decl.name as string,
          description: (decl.description as string) || "",
          parameters: decl.parameters
            ? convertGeminiSchema(decl.parameters as Record<string, unknown>)
            : { type: "object", properties: {} },
        },
      });
    }
  }
  return tools;
}

// Lazy-cached OpenAI-format tools
let _openaiTools: OpenAITool[] | null = null;
function getOpenAITools(): OpenAITool[] {
  if (!_openaiTools) _openaiTools = convertToolsToOpenAI(OPENCLAW_TOOLS);
  return _openaiTools;
}

// ---------------------------------------------------------------------------
// DeepSeek / OpenAI-compatible LLM caller
// ---------------------------------------------------------------------------

interface LLMMessage {
  role: "system" | "user" | "assistant" | "tool";
  content?: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: { name: string; arguments: string };
  }>;
  tool_call_id?: string;
}

interface LLMCallResult {
  reply: string;
  toolUsed: string | null;
  toolResult: Record<string, unknown> | null;
}

async function callDeepSeek(
  env: Env,
  systemPrompt: string,
  messages: LLMMessage[],
  maxIterations: number,
  maxTokens: number,
  executeFn: (name: string, args: Record<string, unknown>) => Promise<unknown>,
): Promise<LLMCallResult> {
  const apiUrl = "https://api.deepseek.com/v1/chat/completions";
  const tools = getOpenAITools();
  const allMessages: LLMMessage[] = [{ role: "system", content: systemPrompt }, ...messages];

  let reply = "";
  let toolUsed: string | null = null;
  let toolResult: Record<string, unknown> | null = null;

  for (let iteration = 0; iteration < maxIterations; iteration++) {
    const resp = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
      },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: allMessages,
        tools,
        tool_choice: "auto",
        max_tokens: maxTokens,
        temperature: 0.7,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`DeepSeek API error ${resp.status}: ${errText}`);
    }

    const data = (await resp.json()) as Record<string, unknown>;
    const choices = data.choices as Array<Record<string, unknown>> | undefined;
    if (!choices || choices.length === 0) {
      reply = "No response from LLM.";
      break;
    }

    const msg = choices[0].message as Record<string, unknown>;
    const toolCalls = msg.tool_calls as
      | Array<{ id: string; type: string; function: { name: string; arguments: string } }>
      | undefined;

    if (toolCalls && toolCalls.length > 0) {
      const tc = toolCalls[0];
      const fnName = tc.function.name;
      let fnArgs: Record<string, unknown> = {};
      try {
        fnArgs = JSON.parse(tc.function.arguments || "{}");
      } catch {
        fnArgs = {};
      }

      toolUsed = fnName;
      let result: unknown;
      try {
        result = await executeFn(fnName, fnArgs);
      } catch (err: unknown) {
        result = { error: err instanceof Error ? err.message : String(err) };
      }

      toolResult =
        typeof result === "object" && result !== null
          ? (result as Record<string, unknown>)
          : { result };

      // Add assistant message with tool_calls
      allMessages.push({
        role: "assistant",
        tool_calls: [
          {
            id: tc.id,
            type: "function",
            function: { name: fnName, arguments: tc.function.arguments || "{}" },
          },
        ],
      });

      // Add tool response
      allMessages.push({
        role: "tool",
        tool_call_id: tc.id,
        content: JSON.stringify(toolResult),
      });

      continue;
    }

    // Text reply
    reply = (msg.content as string) || "";
    break;
  }

  if (!reply && toolUsed && toolResult) {
    try {
      reply = JSON.stringify(toolResult, null, 2).slice(0, 3000);
    } catch {
      reply = `Tool ${toolUsed} executed.`;
    }
  } else if (!reply) {
    reply = "No response generated.";
  }

  return { reply, toolUsed, toolResult };
}

// ---------------------------------------------------------------------------
// Gemini Function Declarations — OpenClaw tools (kept in Gemini format, converted at runtime)
// ---------------------------------------------------------------------------

const OPENCLAW_TOOLS = [
  // --- Real-Time Data: Weather, Crypto, Nutrition (FIRST so model sees them before perplexity) ---
  {
    functionDeclarations: [
      {
        name: "get_weather",
        description:
          "Get current weather and forecast for a location. Defaults to Flagstaff AZ (Miles' location). Use for wardrobe suggestions, day planning, outdoor activity advice, morning briefings. ALWAYS prefer this over web_search or perplexity for weather.",
        parameters: {
          type: "OBJECT",
          properties: {
            latitude: { type: "NUMBER", description: "Latitude (default: 35.20 for Flagstaff AZ)" },
            longitude: {
              type: "NUMBER",
              description: "Longitude (default: -111.65 for Flagstaff AZ)",
            },
            days: { type: "NUMBER", description: "Forecast days 1-7 (default: 3)" },
          },
        },
      },
      {
        name: "get_crypto_prices",
        description:
          "Get real-time cryptocurrency prices, 24h change %, market cap, and volume. ALWAYS use this instead of web_search or perplexity_research for any crypto/bitcoin/ethereum/solana price question.",
        parameters: {
          type: "OBJECT",
          properties: {
            coins: {
              type: "STRING",
              description:
                "Comma-separated CoinGecko IDs (e.g. 'bitcoin,ethereum,solana'). Default: 'bitcoin,ethereum'",
            },
            currency: { type: "STRING", description: "Fiat currency code (default: 'usd')" },
          },
        },
      },
      {
        name: "nutrition_lookup",
        description:
          "Look up nutritional info (calories, protein, fat, carbs) for any food using USDA database. ALWAYS use this instead of web_search or perplexity for nutrition/calorie questions.",
        parameters: {
          type: "OBJECT",
          properties: {
            query: {
              type: "STRING",
              description: "Food to search (e.g. 'chicken breast', 'brown rice', 'banana')",
            },
            limit: { type: "NUMBER", description: "Max results (default: 3)" },
          },
          required: ["query"],
        },
      },
    ],
  },
  {
    functionDeclarations: [
      {
        name: "list_jobs",
        description: "List agency jobs, optionally filtered by status",
        parameters: {
          type: "OBJECT",
          properties: {
            status: {
              type: "STRING",
              description: "Filter: pending, analyzing, pr_ready, approved, done, all",
            },
          },
        },
      },
      {
        name: "create_job",
        description: "Create a new autonomous job in the agency queue",
        parameters: {
          type: "OBJECT",
          properties: {
            project: {
              type: "STRING",
              description:
                "Project: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe",
            },
            task: { type: "STRING", description: "Description of the task" },
            priority: { type: "STRING", description: "P0=critical, P1=high, P2=medium, P3=low" },
          },
          required: ["project", "task"],
        },
      },
      {
        name: "get_job",
        description: "Get status of a specific job by ID",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "kill_job",
        description: "Kill a running job",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to kill" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "get_cost_summary",
        description: "Get current API spend and budget status",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "get_agency_status",
        description: "Get combined agency overview: active jobs, costs, agents, alerts",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "list_proposals",
        description: "List proposals in the agency",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "create_proposal",
        description: "Create a proposal for a non-trivial task that needs approval",
        parameters: {
          type: "OBJECT",
          properties: {
            title: { type: "STRING", description: "Short title" },
            description: { type: "STRING", description: "What needs to be done" },
            priority: { type: "STRING", description: "P0-P3" },
            agent_pref: {
              type: "STRING",
              description: "project_manager, coder_agent, hacker_agent, database_agent",
            },
          },
          required: ["title", "description"],
        },
      },
      {
        name: "search_memory",
        description:
          "Search persistent memories for relevant context. Use this to check for pending reminders or recall past decisions.",
        parameters: {
          type: "OBJECT",
          properties: {
            tag: { type: "STRING", description: "Tag to filter by (e.g. 'reminder')" },
            query: { type: "STRING", description: "Text to search for in memory content" },
            limit: { type: "NUMBER", description: "Max results (default 10)" },
          },
        },
      },
      {
        name: "save_memory",
        description:
          "Save an important fact, decision, or REMINDER to long-term memory. When Miles says 'remind me about X tomorrow/later/at 5pm', set remind_at to the ISO timestamp when the reminder should fire. The system will automatically send it via Telegram at that time.",
        parameters: {
          type: "OBJECT",
          properties: {
            content: { type: "STRING", description: "The fact to remember or reminder text" },
            importance: { type: "NUMBER", description: "1-10 scale" },
            tags: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Tags for categorization. Use 'reminder' tag for reminders.",
            },
            remind_at: {
              type: "STRING",
              description:
                "ISO 8601 timestamp for when to send a Telegram reminder (e.g. '2026-02-28T17:00:00-07:00' for 5pm MST). Only set for time-based reminders. Miles is in MST (Arizona, no DST, UTC-7).",
            },
          },
          required: ["content"],
        },
      },
      {
        name: "get_events",
        description: "Get recent system events (job completions, proposals, alerts)",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Number of events (default 20)" },
          },
        },
      },
      {
        name: "list_agents",
        description: "List registered agents and their status",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "get_runner_status",
        description: "Get runner status and active job count",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "spawn_agent",
        description: "Spawn a new tmux Claude Code agent",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "Job identifier" },
            prompt: { type: "STRING", description: "Agent instruction/prompt" },
            use_worktree: { type: "BOOLEAN", description: "Create isolated git worktree" },
          },
          required: ["prompt"],
        },
      },
      {
        name: "send_chat_to_gateway",
        description:
          "Delegate a complex question to the VPS gateway (Claude Opus specialist agent)",
        parameters: {
          type: "OBJECT",
          properties: {
            message: { type: "STRING", description: "The message to send" },
            agent_id: { type: "STRING", description: "Target agent: coder, hacker, database" },
          },
          required: ["message"],
        },
      },
      {
        name: "get_gmail_inbox",
        description: "Read recent Gmail messages",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Number of emails (default 10)" },
          },
        },
      },
      {
        name: "get_calendar_today",
        description: "Get today's Google Calendar events",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "create_calendar_event",
        description: "Create a new Google Calendar event. Use Arizona time (MST, UTC-7).",
        parameters: {
          type: "OBJECT",
          properties: {
            summary: { type: "STRING", description: "Event title" },
            start: {
              type: "STRING",
              description: "Start time ISO format e.g. 2026-02-26T09:00:00",
            },
            end: { type: "STRING", description: "End time ISO format e.g. 2026-02-26T10:00:00" },
            location: { type: "STRING", description: "Event location (optional)" },
            description: { type: "STRING", description: "Event description (optional)" },
          },
          required: ["summary", "start", "end"],
        },
      },
      {
        name: "get_calendar_upcoming",
        description: "Get upcoming calendar events for the next N days",
        parameters: {
          type: "OBJECT",
          properties: {
            days: { type: "NUMBER", description: "Number of days to look ahead (default 7)" },
          },
        },
      },
      {
        name: "list_calendars",
        description: "List all Google Calendar calendars available",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "trash_emails",
        description: "Move emails to trash/delete them. Requires message IDs from get_gmail_inbox.",
        parameters: {
          type: "OBJECT",
          properties: {
            message_ids: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "List of Gmail message IDs to trash",
            },
          },
          required: ["message_ids"],
        },
      },
      {
        name: "label_emails",
        description:
          "Add or remove labels on emails. Common labels: STARRED, IMPORTANT, UNREAD, INBOX, SPAM, TRASH",
        parameters: {
          type: "OBJECT",
          properties: {
            message_ids: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "List of Gmail message IDs",
            },
            add_labels: { type: "ARRAY", items: { type: "STRING" }, description: "Labels to add" },
            remove_labels: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Labels to remove",
            },
          },
          required: ["message_ids"],
        },
      },
      {
        name: "send_email",
        description: "Send an email via Gmail",
        parameters: {
          type: "OBJECT",
          properties: {
            to: { type: "STRING", description: "Recipient email address" },
            subject: { type: "STRING", description: "Email subject" },
            body: { type: "STRING", description: "Email body text" },
          },
          required: ["to", "subject", "body"],
        },
      },
      {
        name: "get_gmail_labels",
        description: "List all Gmail labels/folders",
        parameters: { type: "OBJECT", properties: {} },
      },
      // --- GitHub ---
      {
        name: "github_repo_info",
        description: "Get info about a GitHub repository (issues, PRs, status, commits)",
        parameters: {
          type: "OBJECT",
          properties: {
            repo: { type: "STRING", description: "Repository in owner/name format" },
            action: { type: "STRING", description: "What to fetch: issues, prs, status, commits" },
          },
          required: ["repo", "action"],
        },
      },
      {
        name: "github_create_issue",
        description: "Create a GitHub issue on a repository",
        parameters: {
          type: "OBJECT",
          properties: {
            repo: { type: "STRING", description: "Repository in owner/name format" },
            title: { type: "STRING", description: "Issue title" },
            body: { type: "STRING", description: "Issue body/description" },
            labels: { type: "ARRAY", items: { type: "STRING" }, description: "Labels to apply" },
          },
          required: ["repo", "title"],
        },
      },
      // --- Web Research ---
      {
        name: "web_search",
        description: "Search the web for current information",
        parameters: {
          type: "OBJECT",
          properties: {
            query: { type: "STRING", description: "Search query" },
          },
          required: ["query"],
        },
      },
      {
        name: "web_fetch",
        description: "Fetch content from a URL and return readable text",
        parameters: {
          type: "OBJECT",
          properties: {
            url: { type: "STRING", description: "The URL to fetch" },
            extract: { type: "STRING", description: "What to extract: text, links, or all" },
          },
          required: ["url"],
        },
      },
      {
        name: "web_scrape",
        description: "Scrape structured data from a webpage (text, links, headings, code, tables)",
        parameters: {
          type: "OBJECT",
          properties: {
            url: { type: "STRING", description: "URL to scrape" },
            extract: {
              type: "STRING",
              description: "What to extract: text, links, headings, code, tables, all",
            },
            selector: { type: "STRING", description: "CSS selector to target specific elements" },
          },
          required: ["url"],
        },
      },
      {
        name: "research_task",
        description:
          "Research a topic before executing — searches web, fetches docs, returns synthesis",
        parameters: {
          type: "OBJECT",
          properties: {
            topic: { type: "STRING", description: "What to research" },
            depth: { type: "STRING", description: "Research depth: quick, medium, deep" },
          },
          required: ["topic"],
        },
      },
      // --- File Operations ---
      {
        name: "file_read",
        description: "Read contents of a file on the server",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            lines: { type: "NUMBER", description: "Max lines to read" },
            offset: { type: "NUMBER", description: "Start from this line number" },
          },
          required: ["path"],
        },
      },
      {
        name: "file_write",
        description: "Write or append to a file on the server",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            content: { type: "STRING", description: "Content to write" },
            mode: { type: "STRING", description: "Write mode: write or append" },
          },
          required: ["path", "content"],
        },
      },
      {
        name: "file_edit",
        description: "Edit a file by finding and replacing a specific string",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            old_string: { type: "STRING", description: "The exact string to find" },
            new_string: { type: "STRING", description: "The replacement string" },
            replace_all: { type: "BOOLEAN", description: "Replace all occurrences" },
          },
          required: ["path", "old_string", "new_string"],
        },
      },
      {
        name: "glob_files",
        description: "Find files matching a glob pattern",
        parameters: {
          type: "OBJECT",
          properties: {
            pattern: { type: "STRING", description: "Glob pattern (e.g. **/*.py)" },
            path: { type: "STRING", description: "Root directory to search in" },
            max_results: { type: "NUMBER", description: "Max files to return" },
          },
          required: ["pattern"],
        },
      },
      {
        name: "grep_search",
        description: "Search file contents using regex patterns across a codebase",
        parameters: {
          type: "OBJECT",
          properties: {
            pattern: { type: "STRING", description: "Regex pattern to search for" },
            path: { type: "STRING", description: "File or directory to search in" },
            file_pattern: { type: "STRING", description: "Filter files by glob" },
            max_results: { type: "NUMBER", description: "Max matches to return" },
            context_lines: { type: "NUMBER", description: "Lines of context around matches" },
          },
          required: ["pattern"],
        },
      },
      // --- Shell & System ---
      {
        name: "shell_execute",
        description: "Execute a shell command on the server (sandboxed to safe commands)",
        parameters: {
          type: "OBJECT",
          properties: {
            command: { type: "STRING", description: "The shell command to run" },
            cwd: { type: "STRING", description: "Working directory" },
            timeout: { type: "NUMBER", description: "Timeout in seconds" },
          },
          required: ["command"],
        },
      },
      {
        name: "git_operations",
        description:
          "Perform git operations: status, add, commit, push, pull, branch, log, diff, clone, checkout",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Git action: status, add, commit, push, pull, branch, log, diff, clone, checkout",
            },
            args: { type: "STRING", description: "Additional arguments" },
            files: { type: "ARRAY", items: { type: "STRING" }, description: "Files to add" },
            repo_path: { type: "STRING", description: "Path to git repo" },
          },
          required: ["action"],
        },
      },
      {
        name: "install_package",
        description: "Install a package or tool (npm, pip, apt, binary)",
        parameters: {
          type: "OBJECT",
          properties: {
            name: { type: "STRING", description: "Package name" },
            manager: { type: "STRING", description: "Package manager: npm, pip, apt, binary" },
            global_install: { type: "BOOLEAN", description: "Install globally" },
          },
          required: ["name", "manager"],
        },
      },
      {
        name: "process_manage",
        description: "Manage running processes: list, kill, check ports, show top resource users",
        parameters: {
          type: "OBJECT",
          properties: {
            action: { type: "STRING", description: "Action: list, kill, check_port, top" },
            target: { type: "STRING", description: "PID, process name, or port number" },
            signal: { type: "STRING", description: "Signal for kill: TERM, KILL, HUP" },
          },
          required: ["action"],
        },
      },
      // --- Deployment ---
      {
        name: "vercel_deploy",
        description: "Deploy a project to Vercel or manage deployments",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Vercel action: deploy, list, env-set, status, logs",
            },
            project_path: { type: "STRING", description: "Path to project to deploy" },
            production: { type: "BOOLEAN", description: "Deploy to production" },
            project_name: { type: "STRING", description: "Vercel project name" },
            env_key: { type: "STRING", description: "Environment variable key" },
            env_value: { type: "STRING", description: "Environment variable value" },
          },
          required: ["action"],
        },
      },
      // --- Compute Tools ---
      {
        name: "compute_math",
        description:
          "Evaluate mathematical expressions precisely (arithmetic, trig, log, factorial, etc.)",
        parameters: {
          type: "OBJECT",
          properties: {
            expression: {
              type: "STRING",
              description: "Math expression (e.g. 2**64 - 1, math.factorial(20))",
            },
            precision: { type: "NUMBER", description: "Decimal places for float results" },
          },
          required: ["expression"],
        },
      },
      {
        name: "compute_stats",
        description: "Calculate statistics: mean, median, mode, std dev, variance, percentiles",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "ARRAY", items: { type: "NUMBER" }, description: "List of numbers" },
            percentiles: {
              type: "ARRAY",
              items: { type: "NUMBER" },
              description: "Percentiles to calculate",
            },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_sort",
        description: "Sort a list of numbers or strings using O(n log n) algorithms",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "ARRAY", items: { type: "STRING" }, description: "List to sort" },
            reverse: { type: "BOOLEAN", description: "Sort descending" },
            algorithm: {
              type: "STRING",
              description: "Algorithm: auto, mergesort, heapsort, quicksort, timsort",
            },
            key: { type: "STRING", description: "For dicts: key to sort by" },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_search",
        description: "Search/filter data using binary search, linear scan, or regex",
        parameters: {
          type: "OBJECT",
          properties: {
            data: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Data to search through",
            },
            target: { type: "STRING", description: "Value to find" },
            method: { type: "STRING", description: "Search method: binary, linear, filter, regex" },
            condition: { type: "STRING", description: "For filter: Python expression using x" },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_matrix",
        description:
          "Matrix operations: multiply, transpose, determinant, inverse, eigenvalues, solve",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Operation: multiply, transpose, determinant, inverse, eigenvalues, solve",
            },
            matrix_a: {
              type: "ARRAY",
              items: { type: "ARRAY", items: { type: "NUMBER" } },
              description: "First matrix (2D array)",
            },
            matrix_b: {
              type: "ARRAY",
              items: { type: "ARRAY", items: { type: "NUMBER" } },
              description: "Second matrix or vector",
            },
          },
          required: ["action", "matrix_a"],
        },
      },
      {
        name: "compute_prime",
        description:
          "Prime number operations: factorize, primality test, generate primes, find nth prime",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "What to compute: factorize, is_prime, generate, nth_prime",
            },
            n: { type: "NUMBER", description: "The number to test/factorize" },
            limit: { type: "NUMBER", description: "Upper bound for generate action" },
          },
          required: ["action", "n"],
        },
      },
      {
        name: "compute_hash",
        description: "Compute cryptographic hashes: SHA-256, SHA-512, MD5, BLAKE2",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "STRING", description: "String to hash" },
            file_path: { type: "STRING", description: "Hash a file instead" },
            algorithm: {
              type: "STRING",
              description: "Hash algorithm: sha256, sha512, md5, blake2b, sha1",
            },
          },
        },
      },
      {
        name: "compute_convert",
        description:
          "Unit and base conversions: number bases, temperatures, distances, data sizes, timestamps",
        parameters: {
          type: "OBJECT",
          properties: {
            value: { type: "STRING", description: "Value to convert" },
            from_unit: { type: "STRING", description: "Source unit/base" },
            to_unit: { type: "STRING", description: "Target unit/base" },
          },
          required: ["value", "from_unit", "to_unit"],
        },
      },
      // --- Communication & Integrations ---
      {
        name: "send_slack_message",
        description: "Send a message to a Slack channel",
        parameters: {
          type: "OBJECT",
          properties: {
            message: { type: "STRING", description: "The message to send" },
            channel: { type: "STRING", description: "Channel ID" },
          },
          required: ["message"],
        },
      },
      {
        name: "manage_reactions",
        description: "Manage auto-reaction rules (list, add, update, delete, get trigger history)",
        parameters: {
          type: "OBJECT",
          properties: {
            action: { type: "STRING", description: "Action: list, add, update, delete, triggers" },
            rule_id: { type: "STRING", description: "Rule ID for update/delete" },
            rule_data: { type: "OBJECT", description: "Rule fields for add/update" },
          },
          required: ["action"],
        },
      },
      // --- Security ---
      {
        name: "security_scan",
        description: "Run an OXO security scan against a target (IP, domain, or URL)",
        parameters: {
          type: "OBJECT",
          properties: {
            target: { type: "STRING", description: "Target to scan: IP, domain, or URL" },
            scan_type: { type: "STRING", description: "Scan profile: quick, full, web" },
            agents: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Override: explicit list of OXO agent keys",
            },
          },
          required: ["target"],
        },
      },
      // --- Prediction Markets ---
      {
        name: "prediction_market",
        description: "Query Polymarket prediction markets — search, get details, list events",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: search, get_market, list_markets, list_events",
            },
            query: { type: "STRING", description: "Search query" },
            market_id: { type: "STRING", description: "Market ID or slug" },
            tag: { type: "STRING", description: "Event tag filter" },
            limit: { type: "NUMBER", description: "Max results to return" },
          },
          required: ["action"],
        },
      },
      // --- Polymarket Trading (Phase 1: read-only intelligence) ---
      {
        name: "polymarket_prices",
        description:
          "Real-time Polymarket prices. 'snapshot' gives midpoint+spread+last trade for YES/NO with mispricing flag. Granular: spread, midpoint, book (order book), last_trade, history.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: snapshot (full overview), spread, midpoint, book, last_trade, history",
            },
            market_id: { type: "STRING", description: "Market slug or numeric ID" },
            token_id: {
              type: "STRING",
              description: "CLOB token ID (0x...) — auto-resolved from market_id if omitted",
            },
            interval: {
              type: "STRING",
              description: "Price history interval: 1m, 1h, 6h, 1d, 1w, max",
            },
            fidelity: { type: "NUMBER", description: "Number of data points for history" },
          },
          required: ["action"],
        },
      },
      {
        name: "polymarket_monitor",
        description:
          "Monitor Polymarket markets. Mispricing detector checks YES+NO sum vs $1.00. Also: open_interest, volume, holders, leaderboard (top traders), health.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: mispricing (arb detector), open_interest, volume, holders, leaderboard, health",
            },
            market_id: { type: "STRING", description: "Market slug or numeric ID" },
            condition_id: { type: "STRING", description: "Market condition ID (0x...)" },
            event_id: { type: "STRING", description: "Event ID for volume queries" },
            period: { type: "STRING", description: "Leaderboard period: day, week, month, all" },
            order_by: { type: "STRING", description: "Leaderboard order: pnl or vol" },
            limit: { type: "NUMBER", description: "Max results" },
          },
          required: ["action"],
        },
      },
      {
        name: "polymarket_portfolio",
        description:
          "View any Polymarket wallet's positions, trades, on-chain activity (read-only). Works with any public address.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: positions (open), closed, trades, value (total), activity (on-chain), profile",
            },
            address: { type: "STRING", description: "Wallet address (0x...)" },
            limit: { type: "NUMBER", description: "Max results" },
          },
          required: ["action", "address"],
        },
      },
      // --- Trading Engine Phase 2 ---
      {
        name: "kalshi_markets",
        description:
          "Search and view Kalshi prediction market data (read-only, no auth needed). Actions: search, get, orderbook, trades, candlesticks, events.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: search, get, orderbook, trades, candlesticks, events",
            },
            ticker: { type: "STRING", description: "Market ticker" },
            query: { type: "STRING", description: "Search keyword" },
            event_ticker: { type: "STRING", description: "Event ticker filter" },
            status: { type: "STRING", description: "Market status: open, closed, settled" },
            limit: { type: "NUMBER", description: "Max results (default: 20)" },
          },
          required: ["action"],
        },
      },
      {
        name: "kalshi_trade",
        description:
          "Place/cancel Kalshi orders. Safety-checked, dry-run by default. Actions: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders. Amounts in cents.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders",
            },
            ticker: { type: "STRING", description: "Market ticker" },
            side: { type: "STRING", description: "Side: yes or no" },
            price: { type: "NUMBER", description: "Price in cents (1-99)" },
            count: { type: "NUMBER", description: "Number of contracts" },
            order_id: { type: "STRING", description: "Order ID (for cancel)" },
            dry_run: {
              type: "BOOLEAN",
              description: "Simulate without real order (default: true)",
            },
          },
          required: ["action"],
        },
      },
      {
        name: "kalshi_portfolio",
        description:
          "View Kalshi portfolio: balance, positions, fills, settlements. Requires API credentials.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: balance, positions, fills, settlements, summary",
            },
            limit: { type: "NUMBER", description: "Max results (default: 50)" },
          },
          required: ["action"],
        },
      },
      {
        name: "polymarket_trade",
        description:
          "Place/cancel Polymarket orders. Routes through proxy to bypass US geoblock. Safety-checked, dry-run default. Actions: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders",
            },
            market_id: { type: "STRING", description: "Market slug or ID" },
            side: { type: "STRING", description: "Side: yes or no" },
            price: { type: "NUMBER", description: "Price (0.01-0.99)" },
            size: { type: "NUMBER", description: "Number of shares" },
            order_id: { type: "STRING", description: "Order ID (for cancel)" },
            dry_run: {
              type: "BOOLEAN",
              description: "Simulate without real order (default: true)",
            },
          },
          required: ["action"],
        },
      },
      {
        name: "arb_scanner",
        description:
          "Cross-platform arbitrage scanner for Polymarket + Kalshi. Actions: scan (auto-match events), compare (keyword), bonds (>90% contracts), mispricing (YES+NO != $1.00).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: scan, compare, bonds, mispricing",
            },
            query: { type: "STRING", description: "Search keyword to filter markets" },
            min_edge: { type: "NUMBER", description: "Minimum price edge (default: 0.02)" },
            max_results: { type: "NUMBER", description: "Max results (default: 10)" },
          },
          required: ["action"],
        },
      },
      {
        name: "trading_strategies",
        description:
          "Automated opportunity scanners. Actions: bonds (>90%), mispricing (gaps), whale_alerts (top wallets), trending (volume), expiring (closing soon), summary (all scanners).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: bonds, mispricing, whale_alerts, trending, expiring, summary",
            },
            params: {
              type: "OBJECT",
              description: "Strategy params (query, limit, min_edge, hours, etc.)",
              properties: {},
            },
          },
          required: ["action"],
        },
      },
      {
        name: "trading_safety",
        description:
          "Manage trading safety: dry-run toggle, kill switch, limits, audit log. Actions: status, get_config, set_config, trade_log, kill_switch, reset.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: status, get_config, set_config, trade_log, kill_switch, reset",
            },
            config: {
              type: "OBJECT",
              description:
                "Config fields to update (for set_config): dry_run, kill_switch, confirm_threshold_cents, max_per_market_cents, max_total_exposure_cents",
              properties: {},
            },
          },
          required: ["action"],
        },
      },
      // --- Sportsbook Odds + Betting Engine (Phase 3) ---
      {
        name: "sportsbook_odds",
        description:
          "Live sportsbook odds from 200+ bookmakers. Actions: sports (list in-season), odds (live odds for a sport), event (all markets for one game), compare (side-by-side bookmaker comparison), best_odds (best line across all books).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: sports, odds, event, compare, best_odds",
            },
            sport: {
              type: "STRING",
              description:
                "Sport key: basketball_nba, americanfootball_nfl, baseball_mlb, icehockey_nhl",
            },
            market: {
              type: "STRING",
              description: "Market: h2h (moneyline), spreads, totals. Default: h2h",
            },
            bookmakers: { type: "STRING", description: "Comma-separated bookmaker keys to filter" },
            event_id: { type: "STRING", description: "Event ID for action=event" },
            limit: { type: "NUMBER", description: "Max results (default: 10)" },
          },
          required: ["action"],
        },
      },
      {
        name: "sportsbook_arb",
        description:
          "Sportsbook arbitrage + EV scanner. Actions: scan (arbs where implied probs < 100%), calculate (optimal stakes for an arb), ev_scan (compare soft book odds vs Pinnacle sharp line, flag +EV bets).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: scan, calculate, ev_scan",
            },
            sport: { type: "STRING", description: "Sport key (default: basketball_nba)" },
            event_id: { type: "STRING", description: "Event ID for action=calculate" },
            min_profit: { type: "NUMBER", description: "Min arb profit % (default: 0)" },
            min_ev: { type: "NUMBER", description: "Min EV threshold (default: 0.01 = 1%)" },
            limit: { type: "NUMBER", description: "Max results (default: 10)" },
          },
          required: ["action"],
        },
      },
      {
        name: "sports_predict",
        description:
          "XGBoost-powered NBA game predictions. Actions: predict (today's games + win probs), evaluate (model accuracy, Brier score), train (retrain on 3 seasons), features (model weights), compare (predictions vs odds → +EV picks).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: predict, evaluate, train, features, compare",
            },
            sport: { type: "STRING", description: "Sport: nba (default)" },
            team: { type: "STRING", description: "Team name or abbreviation" },
            date: { type: "STRING", description: "Date YYYY-MM-DD (default: today)" },
            limit: { type: "NUMBER", description: "Max results (default: 10)" },
          },
          required: ["action"],
        },
      },
      {
        name: "sports_betting",
        description:
          "Full betting pipeline: XGBoost predictions + live odds + EV + Kelly sizing. Actions: recommend (full pipeline with picks), bankroll (Kelly-sized recs for a bankroll), dashboard (multi-sport opportunity summary).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: recommend, bankroll, dashboard",
            },
            sport: { type: "STRING", description: "Sport: nba (default)" },
            bankroll: { type: "NUMBER", description: "Bankroll in USD (default: 100)" },
            min_ev: { type: "NUMBER", description: "Min EV threshold (default: 0.01)" },
            limit: { type: "NUMBER", description: "Max results (default: 10)" },
          },
          required: ["action"],
        },
      },
      // --- Prediction Tracker ---
      {
        name: "prediction_tracker",
        description:
          "Track sports predictions and results over time. Actions: log (save today's predictions before games start), check (grade a day's predictions against actual NBA scores), record (overall track record — accuracy, ROI, best/worst days), yesterday (grade yesterday + show results).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: log, check, record, yesterday",
            },
            date: {
              type: "STRING",
              description: "Date YYYY-MM-DD (default: today for log, yesterday for check)",
            },
            bankroll: {
              type: "NUMBER",
              description: "Bankroll in USD for logging recommendations (default: 100)",
            },
          },
          required: ["action"],
        },
      },
      // --- Deep Research ---
      {
        name: "deep_research",
        description:
          "Multi-step autonomous deep research. Breaks complex questions into sub-questions, researches each in parallel, synthesizes into a structured report with citations. Modes: general, market, technical, academic, news, due_diligence. Depth: quick (~30s), medium (~1min), deep (~2min).",
        parameters: {
          type: "OBJECT",
          properties: {
            query: {
              type: "STRING",
              description: "The research question or topic to investigate thoroughly",
            },
            depth: {
              type: "STRING",
              description: "Depth: quick (3 sub-Qs), medium (5), deep (8). Default: medium",
            },
            mode: {
              type: "STRING",
              description:
                "Domain: general, market (competitors/sizing), technical (architecture/benchmarks), academic (papers), news (recent events), due_diligence (red flags/risks). Default: general",
            },
            max_sources: {
              type: "NUMBER",
              description: "Override max API calls (default: auto, max: 8)",
            },
          },
          required: ["query"],
        },
      },
      // --- Environment ---
      {
        name: "env_manage",
        description: "Manage environment variables and .env files",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: get, set, list, load_dotenv, save_dotenv",
            },
            key: { type: "STRING", description: "Env var name" },
            value: { type: "STRING", description: "Value to set" },
            filter: { type: "STRING", description: "Filter pattern for list" },
            env_file: { type: "STRING", description: "Path to .env file" },
          },
          required: ["action"],
        },
      },
      // --- Job Approval ---
      {
        name: "approve_job",
        description: "Approve a job that is in pr_ready status for execution",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to approve" },
          },
          required: ["job_id"],
        },
      },
      // --- Reflexion (Agency Learning) ---
      {
        name: "get_reflections",
        description:
          "Get past job reflections — the agency's learning memory. Use to check what worked/failed before.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: stats (summary), list (recent), search (find similar)",
            },
            task: {
              type: "STRING",
              description: "Task description to search for (for search action)",
            },
            project: { type: "STRING", description: "Filter by project name" },
            limit: { type: "NUMBER", description: "Max results" },
          },
          required: ["action"],
        },
      },
      {
        name: "create_event",
        description:
          "Create/emit an event to the OpenClaw event engine. Use for logging custom events, milestones, or triggers.",
        parameters: {
          type: "OBJECT",
          properties: {
            event_type: {
              type: "STRING",
              description:
                "Event type: job.created, job.completed, job.failed, deploy.complete, cost.alert, custom, etc.",
            },
            data: {
              type: "OBJECT",
              description: "Event payload data (any key-value pairs)",
              properties: {},
            },
          },
          required: ["event_type"],
        },
      },
      {
        name: "plan_my_day",
        description:
          "Plan the user's day: fetches calendar events, pending jobs, agency status, emails, and AI news highlights to create a prioritized daily plan. Call this when the user asks to plan their day or wants a morning briefing.",
        parameters: {
          type: "OBJECT",
          properties: {
            focus: {
              type: "STRING",
              description: "Optional focus area: work, personal, or all (default: all)",
            },
          },
        },
      },
      {
        name: "plan_my_week",
        description:
          "Plan the user's entire week: fetches 7 days of calendar events, deadlines, reminders, and creates a day-by-day time-blocked schedule around classes and work shifts. Call when user says 'plan my week' or 'weekly plan'.",
        parameters: {
          type: "OBJECT",
          properties: {
            focus: {
              type: "STRING",
              description: "Optional focus: school, work, personal, or all (default: all)",
            },
          },
        },
      },
      // --- Perplexity Deep Research ---
      {
        name: "perplexity_research",
        description:
          "Deep research using Perplexity Sonar — returns AI-synthesized answers with web citations. Better than web_search for complex questions requiring synthesis. DO NOT use for weather (use get_weather), crypto prices (use get_crypto_prices), or nutrition (use nutrition_lookup).",
        parameters: {
          type: "OBJECT",
          properties: {
            query: { type: "STRING", description: "Research question" },
            model: {
              type: "STRING",
              description: "Model: sonar (fast, cheap) or sonar-pro (deeper). Default: sonar",
            },
            focus: {
              type: "STRING",
              description: "Search focus: web, academic, or news. Default: web",
            },
          },
          required: ["query"],
        },
      },
      // --- AI News & Social Media ---
      {
        name: "read_ai_news",
        description:
          "Fetch latest AI news from RSS feeds (OpenAI, DeepMind, HuggingFace, arXiv, The Verge, Ars Technica, TechCrunch, Hacker News, MIT Tech Review). Returns article titles, summaries, and links.",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Max articles to return (default: 10)" },
            source: {
              type: "STRING",
              description:
                "Filter to specific source: openai, deepmind, huggingface, arxiv, verge, arstechnica, techcrunch, hackernews, mittech",
            },
            hours: {
              type: "NUMBER",
              description:
                "Only return articles from last N hours (default: 24). Use 72 or 168 for less frequent sources.",
            },
          },
        },
      },
      {
        name: "read_tweets",
        description:
          "Read recent AI community posts from Reddit (r/MachineLearning, r/artificial, r/LocalLLaMA), Bluesky, or Twitter. Returns posts with text, links, and platform.",
        parameters: {
          type: "OBJECT",
          properties: {
            account: {
              type: "STRING",
              description:
                "Twitter/Bluesky username to read (without @). Leave empty for aggregated AI community feed.",
            },
            limit: { type: "NUMBER", description: "Max posts per source (default: 5)" },
          },
        },
      },
      // --- Proposal Generator ---
      {
        name: "generate_proposal",
        description:
          "Generate a branded HTML client proposal for OpenClaw. Creates a professional document with executive summary, service details, pricing, case studies, timeline, and terms. Saves to server. Use when a potential client needs a formal proposal.",
        parameters: {
          type: "OBJECT",
          properties: {
            business_name: {
              type: "STRING",
              description: "Name of the client's business",
            },
            business_type: {
              type: "STRING",
              description:
                "Type of business: restaurant, barbershop, dental, auto, realestate, other",
            },
            owner_name: {
              type: "STRING",
              description: "Name of the business owner",
            },
            selected_services: {
              type: "ARRAY",
              items: { type: "STRING" },
              description:
                "Services to include: receptionist ($1500), website ($2500), crm ($3000), full_package ($5500 bundle)",
            },
            custom_notes: {
              type: "STRING",
              description: "Optional custom notes or special requirements",
            },
          },
          required: ["business_name", "business_type", "owner_name", "selected_services"],
        },
      },
    ],
  },
  // --- Lead Finder (Google Maps/Search) ---
  {
    functionDeclarations: [
      {
        name: "find_leads",
        description:
          "Search Google Maps and web for real local businesses. Finds restaurants, barbershops, dental offices, auto shops, real estate etc. Returns business name, phone, address, website, rating. Saves leads automatically. Use when Miles wants to find potential clients or prospect for new business.",
        parameters: {
          type: "OBJECT",
          properties: {
            business_type: {
              type: "STRING",
              description:
                "Type of business: restaurants, barbershops, dental offices, auto repair shops, real estate agencies, etc.",
            },
            location: {
              type: "STRING",
              description: "City and state. Default: Flagstaff, AZ",
            },
            limit: {
              type: "INTEGER",
              description: "Max leads to find. Default: 10",
            },
          },
          required: ["business_type"],
        },
      },
    ],
  },
  // --- Sales Caller (Vapi + ElevenLabs outbound calls) ---
  {
    functionDeclarations: [
      {
        name: "sales_call",
        description:
          "Make an AI outbound sales call to a business using Vapi + ElevenLabs. The AI introduces OpenClaw, pitches services, handles objections, and books meetings. Use when Miles wants to call leads or prospects.",
        parameters: {
          type: "OBJECT",
          properties: {
            phone: { type: "STRING", description: "Phone number to call" },
            business_name: { type: "STRING", description: "Business name" },
            business_type: {
              type: "STRING",
              description: "Type: restaurant, barbershop, dental, auto, real_estate",
            },
            owner_name: { type: "STRING", description: "Owner name if known" },
          },
          required: ["phone", "business_name"],
        },
      },
    ],
  },
  // --- SMS / Phone ---
  {
    functionDeclarations: [
      {
        name: "send_sms",
        description:
          "Send an SMS text message via Twilio. Use to notify Miles, send alerts, or communicate with clients. Rate limited to 10/hour.",
        parameters: {
          type: "OBJECT",
          properties: {
            to: {
              type: "STRING",
              description: "Phone number in E.164 format (e.g. +15551234567)",
            },
            body: {
              type: "STRING",
              description: "Message text (max 1600 chars)",
            },
          },
          required: ["to", "body"],
        },
      },
      {
        name: "sms_history",
        description:
          "Get recent SMS messages sent or received. Use to check delivery status or see conversation history.",
        parameters: {
          type: "OBJECT",
          properties: {
            direction: {
              type: "STRING",
              description: "Filter by direction: sent, received, or all (default: all)",
            },
            limit: {
              type: "INTEGER",
              description: "Max messages to return (default: 10)",
            },
          },
        },
      },
    ],
  },
  // --- PinchTab Browser Automation ---
  {
    functionDeclarations: [
      {
        name: "browser_navigate",
        description:
          "Navigate the browser to a URL. Returns page title and URL. Use for web scraping, form filling, and automation.",
        parameters: {
          type: "OBJECT",
          properties: {
            url: { type: "STRING", description: "URL to navigate to" },
          },
          required: ["url"],
        },
      },
      {
        name: "browser_snapshot",
        description:
          "Get the current page's accessibility tree. Returns structured elements with refs (e0, e1, etc.) for interaction.",
        parameters: {
          type: "OBJECT",
          properties: {
            compact: {
              type: "BOOLEAN",
              description: "Compact output (default: true)",
            },
          },
        },
      },
      {
        name: "browser_action",
        description:
          "Perform an action on a page element by its ref. Actions: click, type, fill, press, hover, scroll, select, focus, humanClick, humanType.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Action: click, type, fill, press, hover, scroll, select, focus, humanClick, humanType",
            },
            ref: {
              type: "STRING",
              description: "Element ref from snapshot (e.g. e5)",
            },
            value: {
              type: "STRING",
              description: "Value for type/fill/press/select actions",
            },
          },
          required: ["action", "ref"],
        },
      },
      {
        name: "browser_text",
        description:
          "Extract text content from the current page. Modes: readability (clean article text) or raw (all text).",
        parameters: {
          type: "OBJECT",
          properties: {
            mode: {
              type: "STRING",
              description: "Extraction mode: readability or raw (default: readability)",
            },
          },
        },
      },
      {
        name: "browser_screenshot",
        description: "Take a JPEG screenshot of the current page. Returns base64-encoded image.",
        parameters: {
          type: "OBJECT",
          properties: {},
        },
      },
      {
        name: "browser_tabs",
        description:
          "Manage browser tabs. Actions: list, open (new tab with URL), close (by tab ID).",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: list, open, close (default: list)",
            },
            url: { type: "STRING", description: "URL for open action" },
            tab_id: { type: "STRING", description: "Tab ID for close action" },
          },
        },
      },
      {
        name: "browser_evaluate",
        description:
          "Execute JavaScript in the browser page. Returns the expression result. Use for DOM queries, data extraction, and page manipulation.",
        parameters: {
          type: "OBJECT",
          properties: {
            expression: {
              type: "STRING",
              description: "JavaScript expression to evaluate",
            },
          },
          required: ["expression"],
        },
      },
    ],
  },
  // --- PA Integration (bidirectional agency control) ---
  {
    functionDeclarations: [
      {
        name: "pa_create_job",
        description: "Create a job through the PA integration bridge with full tracking",
        parameters: {
          type: "OBJECT",
          properties: {
            project: {
              type: "STRING",
              description:
                "Project: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe",
            },
            task: { type: "STRING", description: "Description of the task" },
            priority: { type: "STRING", description: "P0=critical, P1=high, P2=medium, P3=low" },
          },
          required: ["project", "task"],
        },
      },
      {
        name: "pa_monitor_job",
        description:
          "Monitor a job's live progress including current phase, active tools, and cost",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to monitor" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "pa_cancel_job",
        description: "Cancel a running job via PA bridge (sets kill flag)",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to cancel" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "pa_approve_job",
        description: "Approve a pending job for execution via PA bridge",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to approve" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "pa_escalate_job",
        description: "Escalate a job to a higher-capability agent (e.g. from Kimi to Claude Opus)",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to escalate" },
            target_agent: {
              type: "STRING",
              description: "Target agent: overseer, elite_coder, debugger, database_agent",
            },
            reason: { type: "STRING", description: "Why this job needs escalation" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "pa_estimate_cost",
        description: "Estimate the cost of a proposed task before creating a job",
        parameters: {
          type: "OBJECT",
          properties: {
            task: { type: "STRING", description: "Task description" },
            agent: {
              type: "STRING",
              description:
                "Preferred agent: coder_agent, elite_coder, hacker_agent, database_agent, code_reviewer, test_generator, architecture_designer, debugger",
            },
          },
          required: ["task"],
        },
      },
      {
        name: "send_telegram_approval",
        description:
          "Send Miles a Telegram message with YES/NO buttons for approval. Use this when a job costs >$0.50 or involves risky actions. Returns immediately — Miles taps the button later.",
        parameters: {
          type: "OBJECT",
          properties: {
            title: { type: "STRING", description: "Short title of what needs approval" },
            description: {
              type: "STRING",
              description: "Details: what will happen, estimated cost, risk level",
            },
            job_id: { type: "STRING", description: "Job ID to approve/reject" },
          },
          required: ["title", "description", "job_id"],
        },
      },
      {
        name: "analyze_tool_gaps",
        description:
          "Analyze job reflections to find missing tools and capabilities. Returns the most-requested missing tools from failed jobs, with frequency counts and suggested implementations. Use this to identify what capabilities the PA should add next.",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: {
              type: "NUMBER",
              description: "Max reflections to analyze (default 50)",
            },
          },
        },
      },
      {
        name: "get_reflections",
        description:
          "Get structured reflections from completed jobs. Each reflection includes what_worked, what_failed, missing_tools, missing_knowledge, suggested_improvements, confidence, and cost. Use to learn from past performance.",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Max reflections to return (default 20)" },
            status: { type: "STRING", description: "Filter by status: success, partial, failure" },
          },
        },
      },
      {
        name: "pa_get_agency_status",
        description: "Get comprehensive agency status: runner, jobs, costs, recent events",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "pa_get_runner_status",
        description: "Get autonomous runner status and active job count",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "pa_list_requests",
        description: "List recent PA integration requests and their statuses",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Max results (default 20)" },
          },
        },
      },
      {
        name: "pa_request_status",
        description: "Check the status of a specific PA request by ID",
        parameters: {
          type: "OBJECT",
          properties: {
            request_id: { type: "STRING", description: "The PA request ID" },
          },
          required: ["request_id"],
        },
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Tool dispatcher — maps function names to gateway API calls
// ---------------------------------------------------------------------------

async function executeTool(
  env: Env,
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  switch (name) {
    case "list_jobs":
      return (
        await gatewayFetch(env, `/api/jobs${args.status ? `?status=${args.status}` : ""}`)
      ).json();
    case "create_job":
      return (
        await gatewayFetch(env, "/api/job/create", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "get_job":
      return (await gatewayFetch(env, `/api/job/${args.job_id}`)).json();
    case "kill_job":
      return (await gatewayFetch(env, `/api/jobs/${args.job_id}/kill`, { method: "POST" })).json();
    case "get_cost_summary":
      return (await gatewayFetch(env, "/api/costs/summary")).json();
    case "get_agency_status":
      return (await gatewayFetch(env, "/api/dashboard/summary")).json();
    case "list_proposals":
      return (await gatewayFetch(env, "/api/proposals")).json();
    case "create_proposal":
      return (
        await gatewayFetch(env, "/api/proposal/create", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "search_memory":
      return (
        await gatewayFetch(
          env,
          `/api/memories?limit=${args.limit || 10}${args.tag ? `&tag=${args.tag}` : ""}${args.query ? `&query=${encodeURIComponent(args.query)}` : ""}`,
        )
      ).json();
    case "save_memory":
      return (
        await gatewayFetch(env, "/api/memory/add", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "get_events":
      return (await gatewayFetch(env, `/api/events?limit=${args.limit || 20}`)).json();
    case "list_agents":
      return (await gatewayFetch(env, "/api/agents")).json();
    case "get_runner_status":
      return (await gatewayFetch(env, "/api/runner/status")).json();
    case "spawn_agent":
      return (
        await gatewayFetch(env, "/api/agents/spawn", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "send_chat_to_gateway":
      return (
        await gatewayFetch(env, "/api/chat", {
          method: "POST",
          body: JSON.stringify({ content: args.message, agent_id: args.agent_id }),
        })
      ).json();
    case "get_gmail_inbox":
      return (await gatewayFetch(env, `/api/gmail/inbox?limit=${args.limit || 10}`)).json();
    case "get_calendar_today":
      return (await gatewayFetch(env, "/api/calendar/today")).json();
    case "create_calendar_event":
      return (
        await gatewayFetch(env, "/api/calendar/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            summary: args.summary,
            start: args.start,
            end: args.end,
            location: args.location || "",
            description: args.description || "",
          }),
        })
      ).json();
    case "get_calendar_upcoming":
      return (await gatewayFetch(env, `/api/calendar/upcoming?days=${args.days || 7}`)).json();
    case "list_calendars":
      return (await gatewayFetch(env, "/api/calendar/list")).json();
    case "trash_emails":
      return (
        await gatewayFetch(env, "/api/gmail/trash", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: args.message_ids }),
        })
      ).json();
    case "label_emails":
      return (
        await gatewayFetch(env, "/api/gmail/label", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message_ids: args.message_ids,
            add_labels: args.add_labels || [],
            remove_labels: args.remove_labels || [],
          }),
        })
      ).json();
    case "send_email":
      return (
        await gatewayFetch(env, "/api/gmail/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to: args.to, subject: args.subject, body: args.body }),
        })
      ).json();
    case "get_gmail_labels":
      return (await gatewayFetch(env, "/api/gmail/labels")).json();
    // --- GitHub ---
    case "github_repo_info":
      return (
        await gatewayFetch(env, "/api/github/repo-info", {
          method: "POST",
          body: JSON.stringify({ repo: args.repo, action: args.action }),
        })
      ).json();
    case "github_create_issue":
      return (
        await gatewayFetch(env, "/api/github/create-issue", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    // --- Web Research ---
    case "web_search":
      return (
        await gatewayFetch(env, "/api/web/search", {
          method: "POST",
          body: JSON.stringify({ query: args.query }),
        })
      ).json();
    case "web_fetch":
      return (
        await gatewayFetch(env, "/api/web/fetch", {
          method: "POST",
          body: JSON.stringify({ url: args.url, extract: args.extract }),
        })
      ).json();
    case "web_scrape":
      return (
        await gatewayFetch(env, "/api/web/scrape", {
          method: "POST",
          body: JSON.stringify({ url: args.url, extract: args.extract, selector: args.selector }),
        })
      ).json();
    case "research_task":
      return (
        await gatewayFetch(env, "/api/research", {
          method: "POST",
          body: JSON.stringify({ topic: args.topic, depth: args.depth }),
        })
      ).json();
    // --- File Operations ---
    case "file_read":
      return (
        await gatewayFetch(env, "/api/file/read", {
          method: "POST",
          body: JSON.stringify({ path: args.path, lines: args.lines, offset: args.offset }),
        })
      ).json();
    case "file_write":
      return (
        await gatewayFetch(env, "/api/file/write", {
          method: "POST",
          body: JSON.stringify({ path: args.path, content: args.content, mode: args.mode }),
        })
      ).json();
    case "file_edit":
      return (
        await gatewayFetch(env, "/api/file/edit", {
          method: "POST",
          body: JSON.stringify({
            path: args.path,
            old_string: args.old_string,
            new_string: args.new_string,
            replace_all: args.replace_all,
          }),
        })
      ).json();
    case "glob_files":
      return (
        await gatewayFetch(env, "/api/file/glob", {
          method: "POST",
          body: JSON.stringify({
            pattern: args.pattern,
            path: args.path,
            max_results: args.max_results,
          }),
        })
      ).json();
    case "grep_search":
      return (
        await gatewayFetch(env, "/api/file/grep", {
          method: "POST",
          body: JSON.stringify({
            pattern: args.pattern,
            path: args.path,
            file_pattern: args.file_pattern,
            max_results: args.max_results,
            context_lines: args.context_lines,
          }),
        })
      ).json();
    // --- Shell & System ---
    case "shell_execute":
      return (
        await gatewayFetch(env, "/api/shell/execute", {
          method: "POST",
          body: JSON.stringify({ command: args.command, cwd: args.cwd, timeout: args.timeout }),
        })
      ).json();
    case "git_operations":
      return (
        await gatewayFetch(env, "/api/git", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            args: args.args,
            files: args.files,
            repo_path: args.repo_path,
          }),
        })
      ).json();
    case "install_package":
      return (
        await gatewayFetch(env, "/api/install", {
          method: "POST",
          body: JSON.stringify({
            name: args.name,
            manager: args.manager,
            global_install: args.global_install,
          }),
        })
      ).json();
    case "process_manage":
      return (
        await gatewayFetch(env, "/api/process", {
          method: "POST",
          body: JSON.stringify({ action: args.action, target: args.target, signal: args.signal }),
        })
      ).json();
    // --- Deployment ---
    case "vercel_deploy":
      return (
        await gatewayFetch(env, "/api/vercel", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    // --- Compute ---
    case "compute_math":
      return (
        await gatewayFetch(env, "/api/compute/math", {
          method: "POST",
          body: JSON.stringify({ expression: args.expression, precision: args.precision }),
        })
      ).json();
    case "compute_stats":
      return (
        await gatewayFetch(env, "/api/compute/stats", {
          method: "POST",
          body: JSON.stringify({ data: args.data, percentiles: args.percentiles }),
        })
      ).json();
    case "compute_sort":
      return (
        await gatewayFetch(env, "/api/compute/sort", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            reverse: args.reverse,
            algorithm: args.algorithm,
            key: args.key,
          }),
        })
      ).json();
    case "compute_search":
      return (
        await gatewayFetch(env, "/api/compute/search", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            target: args.target,
            method: args.method,
            condition: args.condition,
          }),
        })
      ).json();
    case "compute_matrix":
      return (
        await gatewayFetch(env, "/api/compute/matrix", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            matrix_a: args.matrix_a,
            matrix_b: args.matrix_b,
          }),
        })
      ).json();
    case "compute_prime":
      return (
        await gatewayFetch(env, "/api/compute/prime", {
          method: "POST",
          body: JSON.stringify({ action: args.action, n: args.n, limit: args.limit }),
        })
      ).json();
    case "compute_hash":
      return (
        await gatewayFetch(env, "/api/compute/hash", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            file_path: args.file_path,
            algorithm: args.algorithm,
          }),
        })
      ).json();
    case "compute_convert":
      return (
        await gatewayFetch(env, "/api/compute/convert", {
          method: "POST",
          body: JSON.stringify({
            value: args.value,
            from_unit: args.from_unit,
            to_unit: args.to_unit,
          }),
        })
      ).json();
    // --- Communication ---
    case "send_slack_message":
      return (
        await gatewayFetch(env, "/api/slack/send", {
          method: "POST",
          body: JSON.stringify({ message: args.message, channel: args.channel }),
        })
      ).json();
    case "manage_reactions":
      return (
        await gatewayFetch(env, "/api/reactions/manage", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            rule_id: args.rule_id,
            rule_data: args.rule_data,
          }),
        })
      ).json();
    // --- Security ---
    case "security_scan":
      return (
        await gatewayFetch(env, "/api/security/scan", {
          method: "POST",
          body: JSON.stringify({
            target: args.target,
            scan_type: args.scan_type,
            agents: args.agents,
          }),
        })
      ).json();
    // --- Prediction Markets ---
    case "prediction_market":
      return (
        await gatewayFetch(env, "/api/prediction", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            query: args.query,
            market_id: args.market_id,
            tag: args.tag,
            limit: args.limit,
          }),
        })
      ).json();
    case "polymarket_prices":
      return (
        await gatewayFetch(env, "/api/polymarket/prices", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            market_id: args.market_id,
            token_id: args.token_id,
            interval: args.interval,
            fidelity: args.fidelity,
          }),
        })
      ).json();
    case "polymarket_monitor":
      return (
        await gatewayFetch(env, "/api/polymarket/monitor", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            market_id: args.market_id,
            condition_id: args.condition_id,
            event_id: args.event_id,
            period: args.period,
            order_by: args.order_by,
            limit: args.limit,
          }),
        })
      ).json();
    case "polymarket_portfolio":
      return (
        await gatewayFetch(env, "/api/polymarket/portfolio", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            address: args.address,
            limit: args.limit,
          }),
        })
      ).json();
    // --- Trading Engine Phase 2 ---
    case "kalshi_markets":
      return (
        await gatewayFetch(env, "/api/kalshi/markets", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            ticker: args.ticker,
            query: args.query,
            event_ticker: args.event_ticker,
            status: args.status,
            limit: args.limit,
          }),
        })
      ).json();
    case "kalshi_trade":
      return (
        await gatewayFetch(env, "/api/kalshi/trade", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            ticker: args.ticker,
            side: args.side,
            price: args.price,
            count: args.count,
            order_id: args.order_id,
            dry_run: args.dry_run,
          }),
        })
      ).json();
    case "kalshi_portfolio":
      return (
        await gatewayFetch(env, "/api/kalshi/portfolio", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            limit: args.limit,
          }),
        })
      ).json();
    case "polymarket_trade":
      return (
        await gatewayFetch(env, "/api/polymarket/trade", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            market_id: args.market_id,
            side: args.side,
            price: args.price,
            size: args.size,
            order_id: args.order_id,
            dry_run: args.dry_run,
          }),
        })
      ).json();
    case "arb_scanner":
      return (
        await gatewayFetch(env, "/api/arb/scan", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            query: args.query,
            min_edge: args.min_edge,
            max_results: args.max_results,
          }),
        })
      ).json();
    case "trading_strategies":
      return (
        await gatewayFetch(env, "/api/trading/strategies", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            params: args.params,
          }),
        })
      ).json();
    case "trading_safety":
      return (
        await gatewayFetch(env, "/api/trading/safety", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            config: args.config,
          }),
        })
      ).json();
    // --- Sportsbook Odds + Betting Engine (Phase 3) ---
    case "sportsbook_odds":
      return (
        await gatewayFetch(env, "/api/sportsbook/odds", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            sport: args.sport,
            market: args.market,
            bookmakers: args.bookmakers,
            event_id: args.event_id,
            limit: args.limit,
          }),
        })
      ).json();
    case "sportsbook_arb":
      return (
        await gatewayFetch(env, "/api/sportsbook/arb", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            sport: args.sport,
            event_id: args.event_id,
            min_profit: args.min_profit,
            min_ev: args.min_ev,
            limit: args.limit,
          }),
        })
      ).json();
    case "sports_predict":
      return (
        await gatewayFetch(env, "/api/sports/predict", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            sport: args.sport,
            team: args.team,
            date: args.date,
            limit: args.limit,
          }),
        })
      ).json();
    case "sports_betting":
      return (
        await gatewayFetch(env, "/api/sports/betting", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            sport: args.sport,
            bankroll: args.bankroll,
            min_ev: args.min_ev,
            limit: args.limit,
          }),
        })
      ).json();
    // --- Prediction Tracker ---
    case "prediction_tracker":
      return (
        await gatewayFetch(env, "/api/sports/tracker", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            date: args.date,
            bankroll: args.bankroll,
          }),
        })
      ).json();
    // --- Deep Research ---
    case "deep_research":
      return (
        await gatewayFetch(env, "/api/research/deep", {
          method: "POST",
          body: JSON.stringify({
            query: args.query,
            depth: args.depth,
            mode: args.mode,
            max_sources: args.max_sources,
          }),
        })
      ).json();
    // --- Environment ---
    case "env_manage":
      return (
        await gatewayFetch(env, "/api/env", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            key: args.key,
            value: args.value,
            filter: args.filter,
            env_file: args.env_file,
          }),
        })
      ).json();
    // --- Job Approval ---
    case "approve_job":
      return (
        await gatewayFetch(env, `/api/job/${args.job_id}/approve`, { method: "POST" })
      ).json();
    case "get_reflections":
      if (args.action === "stats") {
        return (await gatewayFetch(env, "/api/reflections/stats")).json();
      } else if (args.action === "search") {
        return (
          await gatewayFetch(env, "/api/reflections/search", {
            method: "POST",
            body: JSON.stringify({ task: args.task, project: args.project, limit: args.limit }),
          })
        ).json();
      } else {
        return (
          await gatewayFetch(
            env,
            `/api/reflections?limit=${args.limit || 10}${args.project ? `&project=${args.project}` : ""}`,
          )
        ).json();
      }
    case "create_event":
      return (
        await gatewayFetch(env, "/api/events", {
          method: "POST",
          body: JSON.stringify({
            event_type: args.event_type || "custom",
            data: args.data || {},
          }),
        })
      ).json();
    // --- Perplexity Deep Research ---
    case "perplexity_research": {
      // Smart redirect: if the query matches a dedicated tool, use that instead
      const q = String(args.query || "").toLowerCase();
      if (
        /\b(bitcoin|btc|ethereum|eth|crypto|solana|sol|dogecoin|doge|coin\s*price|token\s*price)\b/.test(
          q,
        )
      ) {
        const coinMap: Record<string, string> = {
          btc: "bitcoin",
          eth: "ethereum",
          sol: "solana",
          doge: "dogecoin",
        };
        const coins = Object.entries(coinMap)
          .filter(([k]) => q.includes(k))
          .map(([, v]) => v);
        if (coins.length === 0) coins.push("bitcoin", "ethereum");
        return executeTool(env, "get_crypto_prices", { coins: coins.join(",") });
      }
      if (/\b(weather|temperature|rain|forecast|snow|wind|humid)\b/.test(q)) {
        return executeTool(env, "get_weather", {});
      }
      if (/\b(calorie|nutrition|protein|macro|carb|fat\s+content|food\s+data)\b/.test(q)) {
        const foodMatch = q.match(/(?:in|of|for)\s+(?:a\s+)?(.+?)(?:\?|$)/);
        return executeTool(env, "nutrition_lookup", { query: foodMatch?.[1] || q });
      }
      const pParams = new URLSearchParams();
      pParams.set("query", String(args.query || ""));
      if (args.model) pParams.set("model", String(args.model));
      if (args.focus) pParams.set("focus", String(args.focus));
      return (await gatewayFetch(env, `/api/perplexity-research?${pParams.toString()}`)).json();
    }
    // --- AI News & Social Media ---
    case "read_ai_news": {
      const params = new URLSearchParams();
      if (args.limit) params.set("limit", String(args.limit));
      if (args.source) params.set("source", String(args.source));
      if (args.hours) params.set("hours", String(args.hours));
      const qs = params.toString();
      return (await gatewayFetch(env, `/api/ai-news${qs ? `?${qs}` : ""}`)).json();
    }
    case "read_tweets": {
      const tParams = new URLSearchParams();
      if (args.account) tParams.set("account", String(args.account));
      if (args.limit) tParams.set("limit", String(args.limit));
      const tqs = tParams.toString();
      return (await gatewayFetch(env, `/api/tweets${tqs ? `?${tqs}` : ""}`)).json();
    }
    case "plan_my_day": {
      const [calRes, upcomingRes, jobsRes, statusRes, emailRes, newsRes, memoriesRes] = await Promise.all([
        gatewayFetch(env, "/api/calendar/today")
          .then((r) => r.json())
          .catch(() => ({ events: [] })),
        gatewayFetch(env, "/api/calendar/upcoming?days=3")
          .then((r) => r.json())
          .catch(() => ({ events: [] })),
        gatewayFetch(env, "/api/jobs?limit=20")
          .then((r) => r.json())
          .catch(() => ({ jobs: [] })),
        gatewayFetch(env, "/api/agency/status")
          .then((r) => r.json())
          .catch(() => ({})),
        gatewayFetch(env, "/api/gmail/inbox?max_results=10")
          .then((r) => r.json())
          .catch(() => ({ messages: [] })),
        gatewayFetch(env, "/api/ai-news?limit=5&hours=24")
          .then((r) => r.json())
          .catch(() => ({ articles: [] })),
        gatewayFetch(env, "/api/memories?tag=reminder&limit=10")
          .then((r) => r.json())
          .catch(() => ({ memories: [] })),
      ]);
      // Determine day of week for schedule context
      const now = new Date();
      const mstOffset = -7 * 60;
      const mstTime = new Date(now.getTime() + (mstOffset + now.getTimezoneOffset()) * 60000);
      const dayOfWeek = mstTime.getDay(); // 0=Sun, 1=Mon, ...
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      return {
        day: dayNames[dayOfWeek],
        is_work_day: dayOfWeek !== 1, // Monday is OFF
        work_shift: dayOfWeek !== 1 ? "5:00pm-10:00pm MST" : "OFF",
        is_monday_off: dayOfWeek === 1, // Monday OFF, maybe soccer
        today_calendar: calRes,
        upcoming_3_days: upcomingRes,
        reminders_and_deadlines: memoriesRes.memories || [],
        pending_jobs: (jobsRes.jobs || []).filter(
          (j: any) => j.status === "pending" || j.status === "analyzing",
        ),
        active_jobs: (jobsRes.jobs || []).filter(
          (j: any) => j.status === "running" || j.status === "in_progress",
        ),
        recent_completed: (jobsRes.jobs || []).filter((j: any) => j.status === "done").slice(0, 5),
        agency_status: statusRes,
        unread_emails: emailRes.messages || emailRes.emails || [],
        ai_news_highlights: newsRes.articles || [],
        focus: args.focus || "all",
        generated_at: mstTime.toISOString(),
        instructions: "Create a specific time-blocked schedule. Factor in: classes from calendar, work shift 5-10pm (except Monday OFF). Monday is OFF work — maybe soccer. Fill gaps with study/project time. Be specific with times, not vague.",
      };
    }
    case "plan_my_week": {
      const [calWeekRes, memoriesRes, jobsRes] = await Promise.all([
        gatewayFetch(env, "/api/calendar/upcoming?days=7")
          .then((r) => r.json())
          .catch(() => ({ events: [] })),
        gatewayFetch(env, "/api/memories?tag=reminder&limit=20")
          .then((r) => r.json())
          .catch(() => ({ memories: [] })),
        gatewayFetch(env, "/api/jobs?limit=20")
          .then((r) => r.json())
          .catch(() => ({ jobs: [] })),
      ]);
      const now = new Date();
      const mstOffset = -7 * 60;
      const mstTime = new Date(now.getTime() + (mstOffset + now.getTimezoneOffset()) * 60000);
      return {
        current_day: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][mstTime.getDay()],
        week_calendar: calWeekRes,
        reminders_and_deadlines: (memoriesRes as { memories?: unknown[] }).memories || [],
        pending_jobs: ((jobsRes as { jobs?: Array<{ status: string }> }).jobs || []).filter(
          (j) => j.status === "pending" || j.status === "analyzing",
        ),
        focus: args.focus || "all",
        schedule_rules: {
          monday: "OFF work — free all day, maybe soccer",
          tue_to_sun: "Part-time job 5:00pm-10:00pm MST",
          classes: "Check calendar events for class times",
          free_blocks: "Before 5pm on workdays (between classes), all day Monday, after 10pm",
        },
        instructions: "Create a FULL WEEK plan, day by day (Mon-Sun). For each day: list classes from calendar with times, add study blocks between classes, mark work shift 5-10pm (except Monday). Flag upcoming deadlines and suggest when to work on them. Be specific with times. Format clearly for Telegram.",
        generated_at: mstTime.toISOString(),
      };
    }
    // --- Proposal Generator ---
    case "generate_proposal":
      return (
        await gatewayFetch(env, "/api/proposals/generate", {
          method: "POST",
          body: JSON.stringify({
            business_name: args.business_name,
            business_type: args.business_type,
            owner_name: args.owner_name,
            selected_services: args.selected_services,
            custom_notes: args.custom_notes,
          }),
        })
      ).json();
    // --- Lead Finder (Google Maps/Search) ---
    case "find_leads":
      return (
        await gatewayFetch(
          env,
          `/api/leads/find?type=${encodeURIComponent(args.business_type || "restaurants")}&location=${encodeURIComponent(args.location || "Flagstaff, AZ")}&limit=${args.limit || 10}`,
        )
      ).json();
    // --- Sales Caller (Vapi outbound) ---
    case "sales_call":
      return (
        await gatewayFetch(env, "/api/calls/make", {
          method: "POST",
          body: JSON.stringify({
            phone: args.phone,
            business_name: args.business_name,
            business_type: args.business_type || "restaurant",
            owner_name: args.owner_name || "",
          }),
        })
      ).json();
    // --- SMS / Phone ---
    case "send_sms":
      return (
        await gatewayFetch(env, "/sms/send", {
          method: "POST",
          body: JSON.stringify({ to: args.to, body: args.body }),
        })
      ).json();
    case "sms_history":
      return (
        await gatewayFetch(
          env,
          `/sms/history?direction=${args.direction || "all"}&limit=${args.limit || 10}`,
        )
      ).json();
    // --- PinchTab Browser Automation ---
    case "browser_navigate":
      return (
        await gatewayFetch(env, "/api/pinch/navigate", {
          method: "POST",
          body: JSON.stringify({ url: args.url }),
        })
      ).json();
    case "browser_snapshot":
      return (await gatewayFetch(env, "/api/pinch/snapshot")).json();
    case "browser_action":
      return (
        await gatewayFetch(env, "/api/pinch/action", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            ref: args.ref,
            value: args.value || "",
          }),
        })
      ).json();
    case "browser_text":
      return (await gatewayFetch(env, `/api/pinch/text?mode=${args.mode || "readability"}`)).json();
    case "browser_screenshot":
      return (await gatewayFetch(env, "/api/pinch/screenshot")).json();
    case "browser_tabs":
      return (
        await gatewayFetch(env, "/api/pinch/tabs", {
          method: "POST",
          body: JSON.stringify({
            action: args.action || "list",
            url: args.url || "",
            tab_id: args.tab_id || "",
          }),
        })
      ).json();
    case "browser_evaluate":
      return (
        await gatewayFetch(env, "/api/pinch/evaluate", {
          method: "POST",
          body: JSON.stringify({ expression: args.expression }),
        })
      ).json();
    // --- PA Integration ---
    case "pa_create_job":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({
            action: "create_job",
            payload: { project: args.project, task: args.task, priority: args.priority || "P1" },
          }),
        })
      ).json();
    case "pa_monitor_job":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({ action: "monitor_job", payload: { job_id: args.job_id } }),
        })
      ).json();
    case "pa_cancel_job":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({ action: "cancel_job", payload: { job_id: args.job_id } }),
        })
      ).json();
    case "pa_approve_job":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({ action: "approve_job", payload: { job_id: args.job_id } }),
        })
      ).json();
    case "pa_escalate_job":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({
            action: "escalate_job",
            payload: {
              job_id: args.job_id,
              target_agent: args.target_agent || "overseer",
              reason: args.reason || "PA escalation",
            },
          }),
        })
      ).json();
    case "pa_estimate_cost":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({
            action: "estimate_cost",
            payload: { task: args.task, agent: args.agent },
          }),
        })
      ).json();
    case "send_telegram_approval": {
      const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
      const ownerId = (env.TELEGRAM_OWNER_ID || "").trim();
      if (!ownerId) return { error: "TELEGRAM_OWNER_ID not set" };

      const approvalText =
        `<b>APPROVAL NEEDED</b>\n\n` +
        `<b>${args.title || "Action"}</b>\n` +
        `${args.description || "No details provided"}\n\n` +
        `Job: <code>${args.job_id}</code>`;

      const sendResp = await fetch(`${tgApi}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: ownerId,
          text: approvalText,
          parse_mode: "HTML",
          reply_markup: {
            inline_keyboard: [
              [
                { text: "YES - Approve", callback_data: `approve:${args.job_id}` },
                { text: "NO - Reject", callback_data: `reject:${args.job_id}` },
              ],
            ],
          },
        }),
      });
      const sendResult = (await sendResp.json()) as Record<string, unknown>;
      return {
        sent: sendResult.ok === true,
        message: sendResult.ok ? "Approval request sent to Telegram" : "Failed to send",
      };
    }
    case "analyze_tool_gaps": {
      try {
        const reflResp = await gatewayFetch(env, `/api/reflections?limit=${args.limit || 50}`);
        if (!reflResp.ok) return { error: "Could not fetch reflections" };
        const reflData = (await reflResp.json()) as {
          reflections?: Array<{
            missing_tools?: string[];
            missing_knowledge?: string[];
            what_failed?: string;
            suggested_improvements?: string[];
            confidence?: number;
          }>;
        };
        const reflections = reflData.reflections || [];
        if (reflections.length === 0) return { message: "No reflections found yet", gaps: [] };

        // Count missing tools frequency
        const toolCounts: Record<string, number> = {};
        const knowledgeCounts: Record<string, number> = {};
        const improvementCounts: Record<string, number> = {};
        let totalFailures = 0;

        for (const r of reflections) {
          if (r.missing_tools) {
            for (const t of r.missing_tools) {
              const key = t.toLowerCase().trim();
              if (key) toolCounts[key] = (toolCounts[key] || 0) + 1;
            }
          }
          if (r.missing_knowledge) {
            for (const k of r.missing_knowledge) {
              const key = k.toLowerCase().trim();
              if (key) knowledgeCounts[key] = (knowledgeCounts[key] || 0) + 1;
            }
          }
          if (r.suggested_improvements) {
            for (const s of r.suggested_improvements) {
              const key = s.toLowerCase().trim();
              if (key) improvementCounts[key] = (improvementCounts[key] || 0) + 1;
            }
          }
          if (r.what_failed) totalFailures++;
        }

        // Sort by frequency
        const sortByFreq = (obj: Record<string, number>) =>
          Object.entries(obj)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 10)
            .map(([item, count]) => ({ item, count }));

        return {
          analyzed: reflections.length,
          total_failures: totalFailures,
          missing_tools: sortByFreq(toolCounts),
          missing_knowledge: sortByFreq(knowledgeCounts),
          suggested_improvements: sortByFreq(improvementCounts),
          recommendation:
            Object.keys(toolCounts).length > 0
              ? `Top priority: Build "${sortByFreq(toolCounts)[0]?.item}" — requested ${sortByFreq(toolCounts)[0]?.count} time(s)`
              : "No tool gaps detected yet. Keep running jobs to build data.",
        };
      } catch (err) {
        return { error: `Analysis failed: ${err}` };
      }
    }
    case "get_reflections": {
      try {
        let url = `/api/reflections?limit=${args.limit || 20}`;
        if (args.status) url += `&status=${args.status}`;
        const resp = await gatewayFetch(env, url);
        if (!resp.ok) return { error: "Could not fetch reflections" };
        return await resp.json();
      } catch (err) {
        return { error: `Failed: ${err}` };
      }
    }
    case "pa_get_agency_status":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({ action: "get_agency_status", payload: {} }),
        })
      ).json();
    case "pa_get_runner_status":
      return (
        await gatewayFetch(env, "/api/pa/request", {
          method: "POST",
          body: JSON.stringify({ action: "get_runner_status", payload: {} }),
        })
      ).json();
    case "pa_list_requests":
      return (await gatewayFetch(env, `/api/pa/requests?limit=${args.limit || 20}`)).json();
    case "pa_request_status":
      return (await gatewayFetch(env, `/api/pa/status/${args.request_id}`)).json();

    // --- Real-Time Data (direct fetch, no gateway needed) ---
    case "get_weather": {
      const lat = (args.latitude as number) || 35.2;
      const lon = (args.longitude as number) || -111.65;
      const days = Math.min((args.days as number) || 3, 7);
      const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,weather_code,sunrise,sunset,uv_index_max&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=${days}&timezone=America%2FPhoenix`;
      try {
        const resp = await fetch(url);
        if (!resp.ok) return { error: `Weather API error: ${resp.status}` };
        const data = (await resp.json()) as Record<string, unknown>;
        const current = data.current as Record<string, unknown>;
        const daily = data.daily as Record<string, unknown[]>;
        const weatherCodes: Record<number, string> = {
          0: "Clear sky",
          1: "Mainly clear",
          2: "Partly cloudy",
          3: "Overcast",
          45: "Foggy",
          48: "Rime fog",
          51: "Light drizzle",
          53: "Drizzle",
          55: "Heavy drizzle",
          61: "Light rain",
          63: "Rain",
          65: "Heavy rain",
          71: "Light snow",
          73: "Snow",
          75: "Heavy snow",
          77: "Snow grains",
          80: "Light showers",
          81: "Showers",
          82: "Heavy showers",
          85: "Light snow showers",
          86: "Heavy snow showers",
          95: "Thunderstorm",
        };
        return {
          location: { latitude: lat, longitude: lon },
          current: {
            temperature_f: current.temperature_2m,
            feels_like_f: current.apparent_temperature,
            humidity_pct: current.relative_humidity_2m,
            precipitation_in: current.precipitation,
            wind_mph: current.wind_speed_10m,
            condition:
              weatherCodes[current.weather_code as number] || `Code ${current.weather_code}`,
          },
          forecast: (daily.time as string[]).map((date: string, i: number) => ({
            date,
            high_f: (daily.temperature_2m_max as number[])[i],
            low_f: (daily.temperature_2m_min as number[])[i],
            precipitation_in: (daily.precipitation_sum as number[])[i],
            rain_chance_pct: (daily.precipitation_probability_max as number[])[i],
            condition:
              weatherCodes[(daily.weather_code as number[])[i]] ||
              `Code ${(daily.weather_code as number[])[i]}`,
            uv_index: (daily.uv_index_max as number[])[i],
            sunrise: (daily.sunrise as string[])[i],
            sunset: (daily.sunset as string[])[i],
          })),
        };
      } catch (e) {
        return { error: `Weather fetch failed: ${(e as Error).message}` };
      }
    }

    case "get_crypto_prices": {
      const coins = (args.coins as string) || "bitcoin,ethereum";
      const currency = (args.currency as string) || "usd";
      const url = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(coins)}&vs_currencies=${currency}&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true`;
      try {
        const resp = await fetch(url, {
          headers: { "User-Agent": "OpenClaw/1.0", Accept: "application/json" },
        });
        if (!resp.ok) return { error: `CoinGecko API error: ${resp.status}` };
        const data = (await resp.json()) as Record<string, Record<string, number>>;
        const result: Record<string, unknown> = {};
        for (const [coin, info] of Object.entries(data)) {
          result[coin] = {
            price: info[currency],
            change_24h_pct: Math.round((info[`${currency}_24h_change`] || 0) * 100) / 100,
            market_cap: info[`${currency}_market_cap`],
            volume_24h: info[`${currency}_24h_vol`],
          };
        }
        return { currency, prices: result };
      } catch (e) {
        return { error: `Crypto fetch failed: ${(e as Error).message}` };
      }
    }

    case "nutrition_lookup": {
      const query = args.query as string;
      if (!query) return { error: "query is required" };
      const limit = Math.min((args.limit as number) || 3, 10);
      const url = `https://api.nal.usda.gov/fdc/v1/foods/search?query=${encodeURIComponent(query)}&pageSize=${limit}&dataType=Foundation,SR%20Legacy&api_key=DEMO_KEY`;
      try {
        const resp = await fetch(url);
        if (!resp.ok) return { error: `USDA API error: ${resp.status}` };
        const data = (await resp.json()) as {
          foods: Array<{
            description: string;
            foodNutrients: Array<{ nutrientName: string; value: number; unitName: string }>;
          }>;
        };
        return {
          query,
          results: data.foods.map((f) => {
            const get = (name: string) => {
              const n = f.foodNutrients.find((fn) =>
                fn.nutrientName.toLowerCase().includes(name.toLowerCase()),
              );
              return n ? `${n.value} ${n.unitName}` : "N/A";
            };
            return {
              food: f.description,
              per_100g: {
                calories: get("Energy"),
                protein: get("Protein"),
                total_fat: get("Total lipid"),
                carbs: get("Carbohydrate"),
                fiber: get("Fiber"),
                sugar: get("Sugars, total"),
                sodium: get("Sodium"),
              },
            };
          }),
        };
      } catch (e) {
        return { error: `Nutrition fetch failed: ${(e as Error).message}` };
      }
    }

    default:
      return { error: `Unknown tool: ${name}` };
  }
}

// Paths whose handler issues internal gateway calls — exempt from rate limiting
// but NOT from auth
const INTERNAL_FANOUT_PATHS = new Set(["/api/status"]);

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const app = new Hono<{ Bindings: Env }>();

// CORS
app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"] }));

// ---------------------------------------------------------------------------
// Auth middleware — skip health / landing / ws endpoints
// ---------------------------------------------------------------------------
app.use("*", async (c, next) => {
  const path = new URL(c.req.url).pathname;

  // Fully public endpoints — no auth, no rate limiting
  if (PUBLIC_PATHS.has(path)) return next();

  // If BEARER_TOKEN is set, enforce it
  const requiredToken = c.env.BEARER_TOKEN;
  if (requiredToken) {
    const auth = c.req.header("Authorization");
    const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
    if (token !== requiredToken) {
      return c.json({ error: "unauthorized" }, 401);
    }
  }

  // Rate limit — skip for internal fan-out paths (they make many gateway
  // calls on behalf of the user but should only cost 1 rate-limit hit)
  if (!INTERNAL_FANOUT_PATHS.has(path)) {
    const ip = c.req.header("CF-Connecting-IP") || "unknown";
    const limit = parseInt(c.env.RATE_LIMIT_PER_MINUTE || "30", 10);
    if (!checkRateLimit(ip, limit)) {
      return c.json({ error: "rate_limited", retry_after_seconds: 60 }, 429);
    }
  }

  return next();
});

// ---------------------------------------------------------------------------
// GET / — Landing page with chat UI
// ---------------------------------------------------------------------------
app.get("/", (c) => {
  const html = LANDING_HTML;
  return new Response(html, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
});

// ---------------------------------------------------------------------------
// GET /health
// ---------------------------------------------------------------------------
app.get("/health", async (c) => {
  // Quick gateway ping
  let gatewayOk = false;
  try {
    const resp = await fetch(`${c.env.GATEWAY_URL}/health`, {
      signal: AbortSignal.timeout(3000),
    });
    gatewayOk = resp.ok;
  } catch {
    gatewayOk = false;
  }

  return c.json({
    status: gatewayOk ? "ok" : "degraded",
    worker: "ok",
    gateway: gatewayOk ? "ok" : "unreachable",
    timestamp: new Date().toISOString(),
    environment: c.env.ENVIRONMENT,
  });
});

// ---------------------------------------------------------------------------
// System prompt for the personal assistant
// ---------------------------------------------------------------------------

function getTodayMST(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/Phoenix" });
}

const SYSTEM_PROMPT = `You are Overseer — Miles's personal AI agency assistant, running on DeepSeek V3 at the Cloudflare edge.

CAPABILITIES: You have live access to the OpenClaw agency via 73 function calls. You can:
- **Jobs & Proposals**: Create, list, kill, approve, and monitor autonomous jobs and proposals
- **GitHub**: Get repo info (issues, PRs, commits), create issues
- **Web Research**: Search the web, fetch/scrape URLs, deep research topics
- **AI News & Social**: Read AI news from RSS feeds (Anthropic, OpenAI, DeepMind, etc.), read tweets from AI accounts
- **File Operations**: Read, write, edit files; glob search; grep across codebases
- **Shell & System**: Execute commands, manage processes, check ports, install packages
- **Git**: Full git operations (status, commit, push, pull, branch, diff, clone, checkout)
- **Deployment**: Vercel deploy, env vars, status, logs
- **Compute**: Math expressions, statistics, sorting, search, matrix ops, primes, hashing, unit conversion
- **Communication**: Send Slack messages, manage auto-reaction rules
- **Security**: Run OXO security scans (Nmap, Nuclei, ZAP)
- **Predictions**: Search/list Polymarket markets (prediction_market)
- **Polymarket Intelligence**: Real-time prices & snapshots (polymarket_prices), arbitrage/mispricing detection (polymarket_monitor), wallet portfolio viewer (polymarket_portfolio)
- **Polymarket Trading**: Place/cancel orders via proxy (polymarket_trade) — dry-run default, safety-checked
- **Kalshi Markets**: Search, get, orderbook, trades, candlesticks (kalshi_markets) — no auth for read-only
- **Kalshi Trading**: Place/cancel orders (kalshi_trade) — dry-run default, safety-checked. Portfolio/balance (kalshi_portfolio)
- **Arbitrage Scanner**: Cross-platform arb detection (arb_scanner) — scan, bonds, mispricing
- **Trading Strategies**: Automated scanners (trading_strategies) — bonds, mispricing, whale alerts, trending, expiring
- **Trading Safety**: Dry-run toggle, kill switch, position limits, trade audit log (trading_safety)
- **Sportsbook Odds**: Live odds from 200+ bookmakers (sportsbook_odds) — moneylines, spreads, totals, best line finder
- **Sportsbook Arb/EV**: Arbitrage scanner + EV detector vs Pinnacle sharp line (sportsbook_arb) — scan, calculate, ev_scan
- **Sports Predictions**: XGBoost NBA win probability model (sports_predict) — predict, train, evaluate, compare to odds
- **Sports Betting**: Full pipeline: predictions + odds + EV + Kelly sizing (sports_betting) — recommend, bankroll, dashboard
- **Prediction Tracker**: Log predictions, grade against actual NBA scores, track accuracy/ROI (prediction_tracker) — log, check, record, yesterday
- **Deep Research**: Multi-step autonomous research engine (deep_research) — breaks questions into sub-Qs, researches in parallel, synthesizes report. Modes: general, market, technical, academic, news, due_diligence
- **Proposal Generator**: Generate branded HTML client proposals (generate_proposal) — tailored to business type, includes pricing, case studies, timeline, terms. Services: receptionist ($1500), website ($2500), crm ($3000), full_package ($5500)
- **Environment**: Manage env vars and .env files
- **Memory**: Search and save persistent memory
- **Agents**: List, spawn, and monitor agents
- **Personal**: Gmail inbox, Google Calendar
- **Costs & Budget**: Real-time spending and budget status
- **Delegation**: Route complex tasks to specialist agents (coder, hacker, database)

PERSONALITY: You're Miles' right-hand — part mentor, part dad, part coach. Warm but direct. You genuinely care about his success, health, and growth.
- Motivate without being corny. Real talk, not generic positivity.
- When he knocks something out, acknowledge it briefly: "That's handled." Not "Great job!!!"
- When he's slacking or forgetting habits, call it out gently but firmly: "You haven't logged water today. Fix that."
- Plan his days like you're looking out for him — sleep, food, hydration, exercise, THEN work.
- Think ahead. If it's Thursday, remind him about soccer. If he hasn't eaten, suggest food.
- Keep messages concise but warm. You're not a robot — you're his personal operations manager who happens to also run an AI agency.
- If a tool call is needed, call it immediately without narrating the intention.

MILES' SCHEDULE:
- NORMAL WEEKS (during semester):
  * Monday: OFF work — big tasks, Claude sessions, weekly planning, maybe soccer
  * Tuesday-Sunday: Part-time job 5pm-10pm MST
  * Classes during the day (check Google Calendar — calendar "as5449@nau.edu" has class schedule)
  * Classes: CENE 499 (Mon/Wed 11:30-12:20), BME 210 (Mon/Wed 12:45-2:00), CENE 499 Lab (Wed 2:20-4:50), ACC 205 (Tue/Thu 9:35-10:50), CENE 486C (Tue/Thu 4:00-5:15), CENE 485C GI Meeting (Tue 4:00-5:00)
  * Between classes: Study blocks, assignments, quick PA tasks
  * After 10pm: Personal time, OpenClaw work, wind down
- SPRING BREAK (Mar 9-14, 2026): NO CLASSES. Working 40 hours at part-time job — shifts are 8am-5pm Mon-Fri. This is a heavy week (~70 hrs total with other commitments). Plan rest, meals, and downtime carefully. Evenings are FREE during spring break (no 5-10pm shift). Prioritize sleep, recovery, and simple meals.
- When planning, ALWAYS check Google Calendar first. The NAU calendar (as5449@nau.edu) is read-only. The W2W Schedule calendar has work shifts. If no W2W events show, ask Miles for his shift times.
- When Miles says "plan my day", ALWAYS call get_calendar_today first to see his actual schedule, then time-block around events + work shift. Be SPECIFIC with times, not vague.
- Example good plan: "9:00-10:15 ACC 205 lecture | 10:30-11:30 Study for exam | 11:30-12:00 Lunch | 12:30-1:45 Engineering lab | 2:00-3:30 Work on Concrete Canoe report | 3:30-4:30 Gym + shower | 5:00-10:00 Work shift"
- Save school deadlines, exam dates, and assignment due dates to memory when Miles mentions them
- WEEKLY PLANNING: Every Sunday at 8am MST, PA sends a full week plan via Telegram. When Miles asks to "plan my week", call get_calendar_upcoming with days=7, then create a day-by-day time-blocked plan with classes, study blocks, work shifts, and deadlines. Be specific.

PROJECTS: OpenClaw (AI agency platform), Delhi Palace (restaurant site), Barber CRM, PrestressCalc (engineering), Concrete Canoe (university project).

ROUTING:
- When Miles says "create a job to X", call create_job immediately.
- When Miles asks about costs/spending/budget, call get_cost_summary.
- BUDGET RULE: Before creating any job estimated to cost >$0.50, use send_telegram_approval to ask Miles first. Include estimated cost and what the job does.
- SELF-IMPROVEMENT: When Miles asks "what tools are we missing?" or "how can you improve?", use analyze_tool_gaps to find patterns in failed jobs. When he asks about past performance, use get_reflections.
- SMART CONTEXT: Monday is OFF work — sometimes soccer. Never schedule part-time work on Mondays.
- When Miles says "what's running" or "status", call get_runner_status or get_agency_status.
- When Miles asks about agents, call list_agents.
- When Miles asks about email/inbox, call get_gmail_inbox. To clean up, use trash_emails. To organize, use label_emails.
- When Miles asks about calendar/schedule, call get_calendar_today or get_calendar_upcoming.
- To create events or plan the day, use create_calendar_event. Always use Arizona time (MST).
- When asked to send email, use send_email. Always confirm recipient before sending.
- For email cleanup: read inbox first, identify junk/spam, then trash them in one call.
- When Miles asks about events/activity, call get_events.
- When Miles asks about a GitHub repo, call github_repo_info.
- When Miles asks to search the web or look something up, call web_search or research_task.
- When Miles asks for deep research, analysis, "look into X thoroughly", "research X", "investigate", "do a deep dive on", or any complex multi-faceted question, use deep_research. Pick the right mode: market (for competitors/business), technical (for tools/frameworks), academic (for papers/studies), news (for recent events), due_diligence (for companies/products). Use perplexity_research only for quick single-question lookups. Use web_search for simple fact checks.
- When Miles asks to generate a proposal, create a proposal for a client, or quote a business, use generate_proposal. Ask for business name, type, owner name, and which services they want if not provided.
- When Miles asks to read/edit/write a file, use file_read/file_edit/file_write.
- When Miles asks to run a command, use shell_execute.
- When Miles asks about git status/commits/push, use git_operations.
- When Miles asks to deploy, use vercel_deploy.
- When Miles asks about WEATHER, temperature, rain, "should I bring a jacket", outdoor plans, or wardrobe advice, ALWAYS use get_weather. Never use web_search or perplexity for weather.
- When Miles asks about CRYPTO PRICES (bitcoin, ethereum, solana, etc), ALWAYS use get_crypto_prices. Never use web_search or perplexity for crypto prices.
- When Miles asks about CALORIES, nutrition, macros, "how much protein in X", use nutrition_lookup. Never use web_search or perplexity for nutrition data.
- When Miles asks to calculate something, use compute_math or compute_stats.
- When Miles asks about predictions/markets, use prediction_market to search/list. For REAL-TIME PRICES, use polymarket_prices with action=snapshot. For arbitrage/mispricing checks, use polymarket_monitor with action=mispricing. For viewing a trader's portfolio, use polymarket_portfolio.
- When Miles asks "what's the price on [market]?", use polymarket_prices(action=snapshot, market_id=slug).
- When Miles asks about arbitrage, opportunities, or "scan for arb", use trading_strategies(action=summary) for a comprehensive scan across both platforms. For specific cross-platform arb only, use arb_scanner(action=scan). For bond-like safe bets, use arb_scanner(action=bonds). For single-market mispricing, use polymarket_monitor(action=mispricing, market_id=slug).
- When Miles asks about top traders or the leaderboard, use polymarket_monitor(action=leaderboard).
- When Miles asks to check a wallet or portfolio, use polymarket_portfolio(action=positions, address=0x...).
- When Miles asks about Kalshi markets, use kalshi_markets(action=search, query=...) to find markets or kalshi_markets(action=get, ticker=...) for details.
- When Miles says "buy" or "trade" on Polymarket, use polymarket_trade. On Kalshi, use kalshi_trade. ALL TRADES ARE DRY-RUN BY DEFAULT — remind Miles to disable dry_run for real trades.
- When Miles asks for trading opportunities or "what should I trade?", use trading_strategies(action=summary) for a full scan, or specific: bonds, mispricing, trending, expiring.
- When Miles asks about trading safety, limits, or kill switch, use trading_safety(action=status). To toggle kill switch: trading_safety(action=kill_switch). To view trade log: trading_safety(action=trade_log).
- CRITICAL: Never place a real trade (dry_run=false) without Miles explicitly confirming. When in doubt, use dry_run=true.
- When Miles asks "what are the odds?", "show me NBA odds", or about sportsbook lines, use sportsbook_odds(action=odds, sport=basketball_nba).
- When Miles asks to "compare odds" or "which book has the best line", use sportsbook_odds(action=best_odds, sport=basketball_nba).
- When Miles asks "scan for +EV", "find value bets", or "are there any +EV bets?", use sportsbook_arb(action=ev_scan, sport=basketball_nba).
- When Miles asks "scan for arbs" on sportsbooks (not prediction markets), use sportsbook_arb(action=scan, sport=basketball_nba).
- When Miles asks "who wins tonight?", "predict the games", or about NBA predictions, use sports_predict(action=predict).
- When Miles asks to train the model or "retrain", use sports_predict(action=train).
- When Miles asks "what should I bet?", "give me picks", or "what NBA bets should I make?", use sports_betting(action=recommend, bankroll=100).
- When Miles asks about model accuracy or evaluation, use sports_predict(action=evaluate).
- For the full pipeline (predictions + odds + EV + Kelly sizing), use sports_betting(action=recommend).
- When Miles asks "how did yesterday go?", "how did my picks do?", or about past prediction results, use prediction_tracker(action=yesterday).
- When Miles asks "what's my record?", "track record", or about overall accuracy/ROI, use prediction_tracker(action=record).
- When Miles asks to log or save today's predictions, use prediction_tracker(action=log).
- When Miles asks to grade or check a specific date's predictions, use prediction_tracker(action=check, date="YYYY-MM-DD").
- When Miles asks to send a Slack message, use send_slack_message.
- When Miles asks about security scanning, use security_scan.
- When Miles asks about AI news, latest developments, or what's happening in AI, call read_ai_news. Use hours=72 for a broader view since some blogs post infrequently.
- When Miles asks about tweets, social posts, or what the AI community is discussing, call read_tweets. This pulls from Reddit AI subs (primary), Bluesky, and Twitter.
- When Miles says "plan my day", call plan_my_day. Use the schedule context to suggest time-blocked todos. Be specific about what to do and when.
- When Miles says "plan my week", "weekly plan", or "what's my week look like", call plan_my_week. Create a day-by-day breakdown with classes, study blocks, work shifts, and deadlines.
- When Miles mentions assignments, deadlines, or homework, save them to memory so plan_my_day can reference them later.
- REMINDERS: When Miles says "remind me to X" or "don't let me forget Y", ALWAYS call save_memory with the 'reminder' tag AND a remind_at timestamp. Convert relative times to ISO 8601 in MST (UTC-7). Examples: "remind me tomorrow" → next day 9am MST, "remind me at 5pm" → today 5pm MST, "remind me in 2 hours" → current time + 2h. The cron system checks every 15 minutes and sends via Telegram automatically.
- When Miles asks "what did I tell you?" or "do I have any reminders?", call search_memory with tag='reminder' to find all saved reminders.
- If PENDING REMINDERS are injected in context, proactively mention them to Miles at the START of your response before addressing his question.
- For complex coding/security/database questions, use send_chat_to_gateway to delegate to a specialist.
`;

// ---------------------------------------------------------------------------
// Telegram table formatter — builds pixel-perfect monospace tables in code
// ---------------------------------------------------------------------------
function formatBettingTable(toolName: string, data: Record<string, unknown> | null): string | null {
  if (!data) return null;

  // sports_betting recommend/bankroll
  if (toolName === "sports_betting" && Array.isArray(data.recommendations)) {
    const recs = data.recommendations as Array<Record<string, unknown>>;
    if (recs.length === 0) return "No +EV bets found right now.";

    const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padEnd(n));
    const rpad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padStart(n));

    let t = "<b>Tonight's Picks</b>\n<pre>\n";
    t +=
      pad("Game", 16) +
      " " +
      pad("Bet", 10) +
      " " +
      pad("Book", 9) +
      " " +
      rpad("Size", 6) +
      " " +
      rpad("EV%", 7) +
      "\n";
    t += "─".repeat(52) + "\n";

    for (const r of recs.slice(0, 8)) {
      const game = String(r.game || "")
        .replace(/ @ /g, " v ")
        .slice(0, 16);
      const bet =
        String(r.bet_on || "")
          .split(" ")
          .pop() || "";
      const book = String(r.book || "").slice(0, 9);
      const size = "$" + Number(r.bet_size || 0).toFixed(0);
      const rawEv = Number(r.ev_pct || 0);
      const ev = rawEv > 999 ? ">999%" : "+" + rawEv.toFixed(1) + "%";
      t +=
        pad(game, 16) +
        " " +
        pad(bet, 10) +
        " " +
        pad(book, 9) +
        " " +
        rpad(size, 6) +
        " " +
        rpad(ev, 7) +
        "\n";
    }
    t += "</pre>";

    const summary = data.summary as Record<string, unknown> | undefined;
    if (summary) {
      t += `\n<b>$${Number(summary.total_wagered || 0).toFixed(0)} wagered</b> · <b>$${Number(summary.total_expected_profit || 0).toFixed(0)} expected profit</b>`;
    }
    return t;
  }

  // sportsbook_arb ev_scan
  if (toolName === "sportsbook_arb" && Array.isArray(data.ev_opportunities)) {
    const opps = data.ev_opportunities as Array<Record<string, unknown>>;
    if (opps.length === 0) return "No +EV bets found vs Pinnacle right now. Markets are efficient.";

    const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padEnd(n));
    const rpad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padStart(n));

    let t = "<b>+EV vs Pinnacle Sharp Line</b>\n<pre>\n";
    t +=
      pad("Game", 16) +
      " " +
      pad("Bet", 10) +
      " " +
      pad("Book", 9) +
      " " +
      rpad("Odds", 5) +
      " " +
      rpad("EV%", 7) +
      "\n";
    t += "─".repeat(51) + "\n";

    for (const o of opps.slice(0, 8)) {
      const game = String(o.game || "")
        .replace(/ @ /g, " v ")
        .slice(0, 16);
      const bet =
        String(o.bet || "")
          .split(" ")
          .pop() || "";
      const book = String(o.book || "").slice(0, 9);
      const odds = Number(o.decimal_odds || 0).toFixed(2);
      const rawEv = Number(o.ev_pct || 0);
      const ev = rawEv > 999 ? ">999%" : "+" + rawEv.toFixed(1) + "%";
      t +=
        pad(game, 16) +
        " " +
        pad(bet, 10) +
        " " +
        pad(book, 9) +
        " " +
        rpad(odds, 5) +
        " " +
        rpad(ev, 7) +
        "\n";
    }
    t += "</pre>";
    t += `\n<b>${opps.length} +EV bets</b> found · ${Number((data.quota as Record<string, unknown>)?.remaining ?? "?")} API calls left`;
    return t;
  }

  // sports_predict predictions
  if (toolName === "sports_predict" && Array.isArray(data.predictions)) {
    const preds = data.predictions as Array<Record<string, unknown>>;
    if (preds.length === 0) return "No NBA games scheduled today.";

    const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padEnd(n));
    const rpad = (s: string, n: number) => (s.length > n ? s.slice(0, n) : s.padStart(n));

    let t = "<b>NBA Predictions</b>\n<pre>\n";
    t += pad("Game", 20) + " " + pad("Pick", 10) + " " + rpad("Prob", 5) + "\n";
    t += "─".repeat(38) + "\n";

    for (const p of preds.slice(0, 10)) {
      const home = String(p.home_abbrev || "").padEnd(3);
      const away = String(p.away_abbrev || "").padEnd(3);
      const game = `${away} @ ${home}`;
      const winner =
        String(p.predicted_winner || "")
          .split(" ")
          .pop() || "";
      const conf = (Number(p.confidence || 0) * 100).toFixed(0) + "%";
      t += pad(game, 20) + " " + pad(winner, 10) + " " + rpad(conf, 5) + "\n";
    }
    t += "</pre>";
    return t;
  }

  // sportsbook_odds compare
  if (toolName === "sportsbook_odds" && Array.isArray(data.comparisons)) {
    const comps = data.comparisons as Array<Record<string, unknown>>;
    if (comps.length === 0) return "No odds data available.";

    let t = "<b>Odds Comparison</b>\n";
    for (const c of comps.slice(0, 5)) {
      t += `\n<b>${c.game}</b>\n<pre>`;
      const books = c.odds_by_book as Record<string, Record<string, number>> | undefined;
      if (books) {
        for (const [bookName, odds] of Object.entries(books)) {
          const line = Object.entries(odds)
            .map(([team, price]) => {
              const short = team.split(" ").pop() || team;
              return `${short} ${Number(price).toFixed(2)}`;
            })
            .join(" | ");
          t += `${bookName.slice(0, 12).padEnd(12)} ${line}\n`;
        }
      }
      t += "</pre>";
    }
    return t;
  }

  // prediction_tracker — check/yesterday results
  if (toolName === "prediction_tracker" && data.summary) {
    const s = data.summary as Record<string, unknown>;
    const date = String(data.date || "");
    const profitSign = Number(s.total_profit || 0) >= 0 ? "+" : "";

    let t = `<b>Results: ${date}</b>\n`;
    t += `Picks: ${s.picks_correct}/${s.picks_total} (${s.picks_pct}%)\n`;
    t += `Bets: ${s.bets_won || 0}/${s.bets_total || 0}\n`;
    t += `Profit: ${profitSign}$${Number(s.total_profit || 0).toFixed(2)} (${profitSign}${s.roi_pct}% ROI)\n`;

    const preds = data.predictions as Array<Record<string, unknown>> | undefined;
    if (preds && preds.length > 0) {
      const pad = (str: string, n: number) => (str.length > n ? str.slice(0, n) : str.padEnd(n));
      t += "\n<pre>\n";
      for (const p of preds.slice(0, 10)) {
        const winner =
          String(p.predicted_winner || "")
            .split(" ")
            .pop() || "";
        const actual =
          String(p.actual_winner || "")
            .split(" ")
            .pop() || "";
        const mark = p.correct === true ? "W" : p.correct === false ? "L" : "?";
        const score = p.home_score ? `${p.away_score}-${p.home_score}` : "";
        t += `${mark} ${pad(winner, 12)} ${pad(score, 8)} (was ${actual})\n`;
      }
      t += "</pre>";
    }
    return t;
  }

  // prediction_tracker — record (overall stats)
  if (toolName === "prediction_tracker" && data.overall) {
    const o = data.overall as Record<string, unknown>;
    const profitSign = Number(o.total_profit || 0) >= 0 ? "+" : "";
    let t = `<b>Track Record (${data.total_days_graded} days)</b>\n`;
    t += `Picks: ${o.picks_correct}/${o.picks_total} (${o.picks_pct}%)\n`;
    t += `Bets: ${o.bets_won}/${o.bets_total} (${o.bets_pct}%)\n`;
    t += `Total wagered: $${Number(o.total_wagered || 0).toFixed(2)}\n`;
    t += `Total profit: ${profitSign}$${Number(o.total_profit || 0).toFixed(2)} (${profitSign}${o.roi_pct}% ROI)`;

    const best = data.best_day as Record<string, unknown> | undefined;
    const worst = data.worst_day as Record<string, unknown> | undefined;
    if (best)
      t += `\n\nBest: ${best.date} (${Number(best.profit || 0) >= 0 ? "+" : ""}$${Number(best.profit || 0).toFixed(2)})`;
    if (worst)
      t += `\nWorst: ${worst.date} (${Number(worst.profit || 0) >= 0 ? "+" : ""}$${Number(worst.profit || 0).toFixed(2)})`;
    return t;
  }

  // prediction_tracker — log confirmation
  if (toolName === "prediction_tracker" && data.status === "logged") {
    return `Predictions logged for ${data.date}: ${data.games} games, ${data.bets} bets saved.`;
  }

  return null;
}

// ---------------------------------------------------------------------------
// POST /webhook/telegram — Telegram bot webhook handler
// ---------------------------------------------------------------------------
app.post("/webhook/telegram", async (c) => {
  const env = c.env;

  // Parse Telegram update
  let update: Record<string, unknown>;
  try {
    update = await c.req.json();
  } catch {
    return c.json({ ok: false }, 400);
  }

  // Handle callback queries (inline keyboard button presses)
  const callbackQuery = update.callback_query as Record<string, unknown> | undefined;
  if (callbackQuery) {
    const cbData = String(callbackQuery.data || "");
    const cbMessage = callbackQuery.message as Record<string, unknown> | undefined;
    const cbChatId = cbMessage ? String((cbMessage.chat as Record<string, unknown>).id) : "";
    const cbMessageId = cbMessage ? String(cbMessage.message_id) : "";
    const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;

    // Parse callback data: "approve:JOB_ID" or "reject:JOB_ID"
    const [action, jobId] = cbData.split(":");

    let responseText = "";
    if (action === "approve" && jobId) {
      try {
        const approveResp = await gatewayFetch(env, `/api/jobs/${jobId}/approve`, { method: "POST" });
        if (approveResp.ok) {
          responseText = `Job ${jobId} APPROVED. Running now.`;
        } else {
          responseText = `Could not approve job ${jobId}. It may have already been processed.`;
        }
      } catch {
        responseText = `Error approving job ${jobId}. Gateway may be down.`;
      }
    } else if (action === "reject" && jobId) {
      try {
        await gatewayFetch(env, `/api/jobs/${jobId}/kill`, { method: "POST" });
        responseText = `Job ${jobId} REJECTED and cancelled.`;
      } catch {
        responseText = `Error rejecting job ${jobId}.`;
      }
    } else {
      responseText = `Unknown action: ${cbData}`;
    }

    // Answer the callback query (removes loading state on button)
    await fetch(`${tgApi}/answerCallbackQuery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        callback_query_id: String(callbackQuery.id),
        text: responseText,
      }),
    });

    // Edit the original message to show the result
    await fetch(`${tgApi}/editMessageText`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: cbChatId,
        message_id: Number(cbMessageId),
        text: responseText,
        parse_mode: "HTML",
      }),
    });

    return c.json({ ok: true });
  }

  const message = update.message as Record<string, unknown> | undefined;
  if (!message || !message.text) {
    return c.json({ ok: true }); // ignore non-text updates
  }

  const chat = message.chat as Record<string, unknown>;
  const chatId = String(chat.id);
  const text = String(message.text);

  // Owner-only check (trim to handle whitespace in secrets)
  const ownerId = (env.TELEGRAM_OWNER_ID || "").trim();
  if (ownerId && chatId !== ownerId) {
    return c.json({ ok: true }); // silently ignore non-owner messages
  }

  // Send "typing" indicator
  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
  c.executionCtx.waitUntil(
    fetch(`${tgApi}/sendChatAction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, action: "typing" }),
    }).catch(() => {}),
  );

  // Load session from KV (keyed by telegram chat)
  const sessionKey = `telegram:${chatId}`;
  let session: SessionData | null = null;
  try {
    const raw = await env.KV_SESSIONS.get(sessionKey);
    if (raw) session = JSON.parse(raw);
  } catch {
    // start fresh
  }

  if (!session) {
    session = {
      messages: [],
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      messageCount: 0,
    };
  }

  // Append user message
  session.messages.push({
    role: "user",
    content: text,
    timestamp: new Date().toISOString(),
  });

  // Pre-fetch pending reminders and recent memories to inject as context
  let reminderContext = "";
  try {
    const [remindersResp, recentMemResp] = await Promise.all([
      gatewayFetch(env, "/api/reminders/due"),
      gatewayFetch(env, "/api/memories?tag=reminder&limit=5"),
    ]);
    const dueReminders: string[] = [];
    if (remindersResp.ok) {
      const data = (await remindersResp.json()) as { reminders?: Array<{ content: string }> };
      for (const r of data.reminders || []) {
        dueReminders.push(`[DUE NOW] ${r.content}`);
      }
    }
    if (recentMemResp.ok) {
      const data = (await recentMemResp.json()) as {
        memories?: Array<{ content: string; remind_at?: string; reminded?: boolean }>;
      };
      for (const m of data.memories || []) {
        if (m.remind_at && !m.reminded && !dueReminders.some((d) => d.includes(m.content))) {
          dueReminders.push(`[UPCOMING] ${m.content} (due: ${m.remind_at})`);
        }
      }
    }
    if (dueReminders.length > 0) {
      reminderContext = `\n\nPENDING REMINDERS FOR MILES:\n${dueReminders.join("\n")}\nIMPORTANT: Proactively mention any due reminders to Miles at the start of your response.`;
    }
  } catch {
    // Don't block the conversation if reminder fetch fails
  }

  // Build conversation messages for DeepSeek (last 20 messages)
  const recentMessages = session.messages.slice(-20);
  const llmMessages: LLMMessage[] = recentMessages.map((m) => ({
    role: (m.role === "assistant" ? "assistant" : "user") as "assistant" | "user",
    content: m.content,
  }));

  // Retrieve relevant memories for context injection
  let memoryContext = "";
  try {
    memoryContext = await getMemoryContext(env.DB, chatId, text, 5);
  } catch {
    // non-fatal — continue without memory context
  }

  const telegramSystemPrompt =
    SYSTEM_PROMPT +
    `\n\nTODAY'S DATE: ${getTodayMST()} (Arizona MST, UTC-7). The year is 2026. Use this for all relative dates ("tomorrow", "next Sunday", etc.).\n\nYou are responding via Telegram. Keep responses SHORT (2-3 sentences max). Tables are auto-formatted by the system — just summarize the key insight briefly. Use HTML: <b>bold</b>, <i>italic</i>. Do NOT use Markdown (* _ # []). Do NOT try to format tables yourself.` +
    reminderContext +
    memoryContext;

  let reply = "";
  let lastToolName = "";
  let lastToolResult: Record<string, unknown> | null = null;

  try {
    const result = await callDeepSeek(
      env,
      telegramSystemPrompt,
      llmMessages,
      3, // max tool iterations
      2048,
      (name, args) => executeTool(env, name, args),
    );
    reply = result.reply;
    lastToolName = result.toolUsed || "";
    lastToolResult = result.toolResult;

    // Override with code-formatted table for betting tools
    const table = formatBettingTable(lastToolName, lastToolResult);
    if (table) {
      reply = table;
    }
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    reply = `Error: ${errMsg}`;
  }

  // Save session
  session.messages.push({
    role: "assistant",
    content: reply,
    timestamp: new Date().toISOString(),
  });
  session.updated = new Date().toISOString();
  session.messageCount = session.messages.length;

  c.executionCtx.waitUntil(
    env.KV_SESSIONS.put(sessionKey, JSON.stringify(session), {
      expirationTtl: 86400,
    }).catch(() => {}),
  );

  // Fire-and-forget: extract facts from user message and store in memory
  c.executionCtx.waitUntil(
    extractAndStore(env.DB, env.DEEPSEEK_API_KEY, chatId, text).catch((err) =>
      console.error("Fact extraction background error:", err),
    ),
  );

  // Send reply via Telegram (split if > 4096 chars)
  const maxLen = 4096;
  const chunks: string[] = [];
  for (let i = 0; i < reply.length; i += maxLen) {
    chunks.push(reply.slice(i, i + maxLen));
  }

  for (const chunk of chunks) {
    try {
      const sendResp = await fetch(`${tgApi}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: chatId,
          text: chunk,
          parse_mode: "HTML",
        }),
      });
      const sendResult = (await sendResp.json()) as Record<string, unknown>;
      if (!sendResult.ok) {
        // HTML parse failed — strip tags and retry as plain text
        const plain = chunk.replace(/<[^>]+>/g, "");
        await fetch(`${tgApi}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: plain }),
        });
      }
    } catch {
      // Network error fallback — send plain text
      const plain = chunk.replace(/<[^>]+>/g, "");
      await fetch(`${tgApi}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: plain }),
      }).catch(() => {});
    }
  }

  return c.json({ ok: true });
});

// ---------------------------------------------------------------------------
// POST /api/chat — DeepSeek-powered chat with tool calling + KV sessions
// ---------------------------------------------------------------------------
app.post("/api/chat", async (c) => {
  const body = await c.req.json<ChatRequest>();
  const { message, sessionKey } = body;

  if (!message) {
    return c.json({ error: "message is required" }, 400);
  }

  const key = sessionKey || `worker:${crypto.randomUUID()}`;

  // Load session from KV
  let session: SessionData | null = null;
  try {
    const raw = await c.env.KV_SESSIONS.get(key);
    if (raw) session = JSON.parse(raw);
  } catch {
    // ignore parse errors, start fresh
  }

  if (!session) {
    session = {
      messages: [],
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      messageCount: 0,
    };
  }

  // Append user message to local session
  session.messages.push({
    role: "user",
    content: message,
    timestamp: new Date().toISOString(),
  });

  // Build conversation messages (last 20 for context)
  const recentMessages = session.messages.slice(-20);
  const llmMessages: LLMMessage[] = recentMessages.map((m) => ({
    role: (m.role === "assistant" ? "assistant" : "user") as "assistant" | "user",
    content: m.content,
  }));

  // Memory context injection for /api/chat
  let chatMemoryContext = "";
  try {
    chatMemoryContext = await getMemoryContext(c.env.DB, key, message, 5);
  } catch {
    // non-fatal
  }

  const chatSystemPrompt =
    SYSTEM_PROMPT +
    `\n\nTODAY'S DATE: ${getTodayMST()} (Arizona MST, UTC-7). The year is 2026.` +
    chatMemoryContext;

  let reply = "";
  let toolUsed: string | null = null;

  try {
    const result = await callDeepSeek(c.env, chatSystemPrompt, llmMessages, 3, 4096, (name, args) =>
      executeTool(c.env, name, args),
    );
    reply = result.reply;
    toolUsed = result.toolUsed;
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return c.json({ error: "llm_fetch_failed", detail: errMsg }, 502);
  }

  // Append assistant response to local session
  session.messages.push({
    role: "assistant",
    content: reply,
    timestamp: new Date().toISOString(),
  });

  session.updated = new Date().toISOString();
  session.messageCount = session.messages.length;

  // Save session to KV (24h TTL)
  try {
    await c.env.KV_SESSIONS.put(key, JSON.stringify(session), {
      expirationTtl: 86400,
    });
  } catch {
    // non-fatal
  }

  // Fire-and-forget: extract facts from user message
  c.executionCtx.waitUntil(
    extractAndStore(c.env.DB, c.env.DEEPSEEK_API_KEY, key, message).catch((err) =>
      console.error("Fact extraction background error:", err),
    ),
  );

  return c.json({
    response: reply,
    model: "deepseek-chat",
    tool_used: toolUsed,
    sessionKey: key,
    sessionMessageCount: session.messageCount,
  });
});

// ---------------------------------------------------------------------------
// GET /api/status — aggregated dashboard view of all gateway subsystems
// (Rate-limit exempt: uses internal fan-out calls to gateway)
// ---------------------------------------------------------------------------
app.get("/api/status", async (c) => {
  const endpoints: Record<string, { path: string; method: string }> = {
    health: { path: "/health", method: "GET" },
    agents: { path: "/api/agents", method: "GET" },
    heartbeat: { path: "/api/heartbeat/status", method: "GET" },
    costs: { path: "/api/costs/summary", method: "GET" },
    quotas: { path: "/api/quotas/status", method: "GET" },
    policy: { path: "/api/policy", method: "GET" },
    events: { path: "/api/events?limit=10", method: "GET" },
    memories: { path: "/api/memories?limit=5", method: "GET" },
    cronJobs: { path: "/api/cron/jobs", method: "GET" },
    jobs: { path: "/api/jobs", method: "GET" },
    proposals: { path: "/api/proposals", method: "GET" },
    routerHealth: { path: "/api/route/health", method: "GET" },
    routerModels: { path: "/api/route/models", method: "GET" },
  };

  const results: Record<string, unknown> = {};
  const statuses: Record<string, string> = {};

  // Fire all requests in parallel
  const entries = Object.entries(endpoints);
  const responses = await Promise.allSettled(
    entries.map(([, cfg]) => gatewayFetch(c.env, cfg.path, { method: cfg.method })),
  );

  for (let i = 0; i < entries.length; i++) {
    const [name] = entries[i];
    const result = responses[i];
    if (result.status === "fulfilled" && result.value.ok) {
      try {
        results[name] = await result.value.json();
        statuses[name] = "ok";
      } catch {
        results[name] = null;
        statuses[name] = "parse_error";
      }
    } else {
      results[name] = null;
      statuses[name] = result.status === "rejected" ? "error" : `http_${result.value.status}`;
    }
  }

  const okCount = Object.values(statuses).filter((s) => s === "ok").length;
  const totalCount = Object.keys(statuses).length;

  return c.json({
    overall:
      okCount === totalCount ? "healthy" : okCount > totalCount / 2 ? "degraded" : "critical",
    subsystems: statuses,
    summary: `${okCount}/${totalCount} subsystems healthy`,
    data: results,
    timestamp: new Date().toISOString(),
  });
});

// ---------------------------------------------------------------------------
// Proxy helpers — GET and POST pass-through to gateway
// ---------------------------------------------------------------------------

/** Create a GET proxy route */
function proxyGet(workerPath: string, gatewayPath?: string) {
  app.get(workerPath, async (c) => {
    // Forward query string
    const url = new URL(c.req.url);
    const qs = url.search;
    const target = (gatewayPath || workerPath) + qs;
    const resp = await gatewayFetch(c.env, target);
    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

/** Create a POST proxy route */
function proxyPost(workerPath: string, gatewayPath?: string) {
  app.post(workerPath, async (c) => {
    const body = await c.req.text();
    const resp = await gatewayFetch(c.env, gatewayPath || workerPath, {
      method: "POST",
      body,
    });
    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

// ---------------------------------------------------------------------------
// Proxy routes — Proposals
// ---------------------------------------------------------------------------
proxyPost("/api/proposal/create");
proxyGet("/api/proposals");

// Parameterized routes need custom handlers (can't use proxyGet helper)
app.get("/api/proposal/:id", async (c) => {
  const id = c.req.param("id");
  const resp = await gatewayFetch(c.env, `/api/proposal/${id}`);
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

// ---------------------------------------------------------------------------
// Proxy routes — Jobs
// ---------------------------------------------------------------------------
proxyGet("/api/jobs");
proxyPost("/api/job/create");

app.get("/api/job/:id", async (c) => {
  const id = c.req.param("id");
  const resp = await gatewayFetch(c.env, `/api/job/${id}`);
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

app.post("/api/job/:id/approve", async (c) => {
  const id = c.req.param("id");
  const body = await c.req.text();
  const resp = await gatewayFetch(c.env, `/api/job/${id}/approve`, {
    method: "POST",
    body,
  });
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

// ---------------------------------------------------------------------------
// Memory API Routes — D1-backed personal memory system (Week 1 CRUD)
// ---------------------------------------------------------------------------

/**
 * Initialize memory tables on first request.
 * This is idempotent, so safe to call multiple times.
 */
let memoryTablesInitialized = false;
async function ensureMemoryTablesExist(db: D1Database): Promise<void> {
  if (!memoryTablesInitialized) {
    await Memory.initializeMemoryTables(db);
    memoryTablesInitialized = true;
  }
}

/** POST /api/v2/memory/add — Add a new memory */
app.post("/api/v2/memory/add", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const body = (await c.req.json()) as Memory.MemoryAddRequest;

    if (!body.data || !body.user_id) {
      return c.json({ error: "Missing required fields: data, user_id" }, 400);
    }

    const result = await Memory.addMemory(env.DB, body);
    return c.json(result, 201);
  } catch (err: unknown) {
    console.error("Error adding memory:", err);
    return c.json({ error: "Failed to add memory" }, 500);
  }
});

/** GET /api/v2/memory/search — Search memories */
app.get("/api/v2/memory/search", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const query = c.req.query("query") || "";
    const userId = c.req.query("user_id") || "";
    const agentId = c.req.query("agent_id");
    const runId = c.req.query("run_id");
    const category = c.req.query("category");
    const limit = parseInt(c.req.query("limit") || "10", 10);

    if (!userId) {
      return c.json({ error: "Missing required query param: user_id" }, 400);
    }

    const results = await Memory.searchMemories(env.DB, {
      query,
      user_id: userId,
      agent_id: agentId,
      run_id: runId,
      category,
      limit,
    });

    return c.json({ results });
  } catch (err: unknown) {
    console.error("Error searching memories:", err);
    return c.json({ error: "Failed to search memories" }, 500);
  }
});

/** GET /api/v2/memory/:id — Get a specific memory */
app.get("/api/v2/memory/:id", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const id = c.req.param("id");
    const memory = await Memory.getMemory(env.DB, id);

    if (!memory) {
      return c.json({ error: "Memory not found" }, 404);
    }

    return c.json({ memory });
  } catch (err: unknown) {
    console.error("Error getting memory:", err);
    return c.json({ error: "Failed to get memory" }, 500);
  }
});

/** PUT /api/v2/memory/:id — Update a memory */
app.put("/api/v2/memory/:id", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const id = c.req.param("id");
    const body = (await c.req.json()) as { data: string; category?: string };

    if (!body.data) {
      return c.json({ error: "Missing required field: data" }, 400);
    }

    const memory = await Memory.updateMemory(env.DB, id, body.data, body.category);
    return c.json({ memory });
  } catch (err: unknown) {
    console.error("Error updating memory:", err);
    return c.json({ error: "Failed to update memory" }, 500);
  }
});

/** DELETE /api/v2/memory/:id — Delete a memory */
app.delete("/api/v2/memory/:id", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const id = c.req.param("id");
    await Memory.deleteMemory(env.DB, id);
    return c.json({ success: true });
  } catch (err: unknown) {
    console.error("Error deleting memory:", err);
    return c.json({ error: "Failed to delete memory" }, 500);
  }
});

/** GET /api/v2/memory/list/:userId — List all memories for a user */
app.get("/api/v2/memory/list/:userId", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const userId = c.req.param("userId");
    const agentId = c.req.query("agent_id");
    const runId = c.req.query("run_id");
    const category = c.req.query("category");
    const limit = parseInt(c.req.query("limit") || "100", 10);

    const memories = await Memory.listMemories(env.DB, userId, {
      agent_id: agentId,
      run_id: runId,
      category,
      limit,
    });

    return c.json({ memories });
  } catch (err: unknown) {
    console.error("Error listing memories:", err);
    return c.json({ error: "Failed to list memories" }, 500);
  }
});

/** GET /api/v2/memory/:id/history — Get audit history for a memory */
app.get("/api/v2/memory/:id/history", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const id = c.req.param("id");
    const limit = parseInt(c.req.query("limit") || "50", 10);

    const history = await Memory.getMemoryHistory(env.DB, id, limit);
    return c.json({ history });
  } catch (err: unknown) {
    console.error("Error getting memory history:", err);
    return c.json({ error: "Failed to get memory history" }, 500);
  }
});

/** GET /api/v2/memory/stats/:userId — Get memory statistics for a user */
app.get("/api/v2/memory/stats/:userId", async (c) => {
  const env = c.env as Env;
  await ensureMemoryTablesExist(env.DB);

  try {
    const userId = c.req.param("userId");
    const stats = await Memory.getMemoryStats(env.DB, userId);
    return c.json({ stats });
  } catch (err: unknown) {
    console.error("Error getting memory stats:", err);
    return c.json({ error: "Failed to get memory stats" }, 500);
  }
});

// ---------------------------------------------------------------------------
// Proxy routes — Events, Memories, Cron, Costs, Policy, Quotas
// ---------------------------------------------------------------------------
proxyGet("/api/events");
proxyGet("/api/memories");
proxyPost("/api/memory/add");
proxyGet("/api/cron/jobs");
proxyGet("/api/costs/summary");
proxyGet("/api/policy");
proxyGet("/api/quotas/status");

// ---------------------------------------------------------------------------
// Proxy routes — Router
// ---------------------------------------------------------------------------
proxyPost("/api/route");
proxyGet("/api/route/models");
proxyGet("/api/route/health");

// ---------------------------------------------------------------------------
// Proxy routes — Agents, Heartbeat
// ---------------------------------------------------------------------------
proxyGet("/api/agents");
proxyGet("/api/heartbeat/status");

// ---------------------------------------------------------------------------
// Landing page HTML — Dark-themed chat UI
// ---------------------------------------------------------------------------
const LANDING_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<title>Overseer — OpenClaw</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#08090c;--surface:#0f1116;--surface-2:#151820;--surface-3:#1a1e28;
  --border:#1e2230;--border-active:#2a3045;
  --text:#d4d8e8;--text-bright:#eef0f8;--text-muted:#6a7094;--text-dim:#3d4260;
  --amber:#e8a832;--amber-dim:#e8a83225;--amber-glow:#e8a83215;
  --red:#e84545;--red-dim:#e8454520;
  --green:#45c882;--green-dim:#45c88220;
  --blue:#4588e8;--blue-dim:#4588e820;
  --purple:#8b5cf6;--purple-dim:#8b5cf620;
  --cyan:#22d3ee;--cyan-dim:#22d3ee20;
  --font-mono:'JetBrains Mono',monospace;
  --font-body:'Outfit',sans-serif;
  --radius:10px;
}
html,body{height:100%;font-family:var(--font-body);-webkit-font-smoothing:antialiased}
body{background:var(--bg);color:var(--text);display:flex;flex-direction:column;overflow:hidden}

/* Noise texture overlay */
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  background-size:128px 128px;
}

/* Header */
.header{
  padding:0 20px;height:56px;background:var(--surface);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:14px;flex-shrink:0;
  position:relative;z-index:10;
}
.header::after{
  content:'';position:absolute;bottom:-1px;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--amber-dim),transparent);
}
.logo-mark{
  width:34px;height:34px;border-radius:8px;position:relative;
  background:linear-gradient(135deg,var(--amber),#c88520);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--font-mono);font-weight:700;font-size:15px;color:var(--bg);
  box-shadow:0 0 20px var(--amber-dim);
}
.logo-mark::after{
  content:'';position:absolute;inset:-2px;border-radius:10px;
  background:linear-gradient(135deg,var(--amber),transparent);
  opacity:.25;z-index:-1;
}
.header-title{
  font-family:var(--font-mono);font-size:14px;font-weight:600;
  color:var(--text-bright);letter-spacing:-.3px;
}
.header-title span{color:var(--text-muted);font-weight:400}
.header-right{margin-left:auto;display:flex;align-items:center;gap:12px}
.session-info{
  font-family:var(--font-mono);font-size:10px;color:var(--text-dim);
  display:flex;align-items:center;gap:6px;
}
.session-info .count{color:var(--text-muted)}
.status-pill{
  display:flex;align-items:center;gap:6px;
  padding:4px 10px 4px 8px;border-radius:20px;
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:.5px;
  background:var(--green-dim);color:var(--green);
  border:1px solid transparent;
  transition:all .3s;
}
.status-pill.offline{background:var(--red-dim);color:var(--red)}
.status-pill.degraded{background:#d2992220;color:#d29922}
.status-pill .dot{
  width:6px;height:6px;border-radius:50%;background:currentColor;
  animation:pulse 2s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* Chat */
.chat{
  flex:1;overflow-y:auto;padding:24px 20px;
  display:flex;flex-direction:column;gap:4px;
  position:relative;z-index:1;
  scroll-behavior:smooth;
}
.chat::-webkit-scrollbar{width:5px}
.chat::-webkit-scrollbar-track{background:transparent}
.chat::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.chat::-webkit-scrollbar-thumb:hover{background:var(--border-active)}

/* Messages */
.msg-group{display:flex;flex-direction:column;gap:2px;max-width:780px;width:100%}
.msg-group.user{align-self:flex-end}
.msg-group.bot{align-self:flex-start}
.msg-label{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:.8px;
  padding:0 4px;margin-bottom:4px;margin-top:16px;
}
.msg-group.user .msg-label{color:var(--blue);text-align:right}
.msg-group.bot .msg-label{color:var(--amber)}

.msg{
  padding:14px 18px;line-height:1.65;font-size:14px;
  word-break:break-word;position:relative;
}
.msg-group.user .msg{
  background:var(--blue-dim);border:1px solid #4588e830;
  border-radius:var(--radius) var(--radius) 4px var(--radius);
  color:var(--text-bright);
}
.msg-group.bot .msg{
  background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--radius) var(--radius) var(--radius) 4px;
}

/* Tool badge */
.tool-badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 10px 3px 7px;border-radius:6px;
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  letter-spacing:.3px;text-transform:uppercase;
  margin-bottom:10px;
  animation:badgeFade .4s ease;
}
@keyframes badgeFade{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.tool-badge.jobs{background:var(--purple-dim);color:var(--purple);border:1px solid #8b5cf630}
.tool-badge.costs{background:var(--green-dim);color:var(--green);border:1px solid #45c88230}
.tool-badge.agents{background:var(--cyan-dim);color:var(--cyan);border:1px solid #22d3ee30}
.tool-badge.memory{background:var(--amber-dim);color:var(--amber);border:1px solid #e8a83230}
.tool-badge.github{background:#24292e;color:#e6edf3;border:1px solid #30363d}
.tool-badge.system{background:var(--surface-3);color:var(--text-muted);border:1px solid var(--border)}
.tool-badge .tool-icon{font-size:12px}

/* Markdown in messages */
.msg h1,.msg h2,.msg h3{color:var(--text-bright);margin:12px 0 6px;font-family:var(--font-body)}
.msg h1{font-size:18px} .msg h2{font-size:16px} .msg h3{font-size:14px;color:var(--amber)}
.msg p{margin:4px 0}
.msg strong{color:var(--text-bright);font-weight:600}
.msg em{color:var(--text-muted);font-style:italic}
.msg a{color:var(--amber);text-decoration:none;border-bottom:1px solid var(--amber-dim)}
.msg a:hover{border-color:var(--amber)}
.msg ul,.msg ol{margin:6px 0 6px 20px}
.msg li{margin:3px 0;line-height:1.5}
.msg li::marker{color:var(--text-dim)}
.msg blockquote{
  border-left:3px solid var(--amber);padding:6px 14px;margin:8px 0;
  background:var(--amber-glow);border-radius:0 6px 6px 0;
  color:var(--text-muted);font-style:italic;
}
.msg hr{border:none;border-top:1px solid var(--border);margin:12px 0}
.msg code{
  font-family:var(--font-mono);font-size:12px;
  background:#ffffff08;padding:2px 6px;border-radius:4px;
  color:var(--amber);border:1px solid #ffffff08;
}
.msg pre{
  background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;overflow-x:auto;margin:10px 0;position:relative;
}
.msg pre code{
  background:none;padding:0;border:none;color:var(--text);
  font-size:12px;line-height:1.6;
}
.msg pre .lang-tag{
  position:absolute;top:6px;right:10px;
  font-family:var(--font-mono);font-size:9px;font-weight:600;
  color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;
}
.msg table{
  width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;
  font-family:var(--font-mono);
}
.msg th{
  text-align:left;padding:8px 12px;border-bottom:2px solid var(--border);
  color:var(--amber);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;
}
.msg td{
  padding:7px 12px;border-bottom:1px solid var(--border);
  color:var(--text);
}
.msg tr:hover td{background:var(--surface-3)}

/* Typing indicator */
.typing{
  display:none;align-self:flex-start;max-width:780px;
  padding:14px 18px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:var(--radius) var(--radius) var(--radius) 4px;
  gap:6px;align-items:center;margin-top:4px;
}
.typing.show{display:flex}
.typing-dots{display:flex;gap:4px;align-items:center}
.typing-dots span{
  width:6px;height:6px;background:var(--amber);border-radius:50%;
  animation:typeBounce .8s infinite alternate;opacity:.4;
}
.typing-dots span:nth-child(2){animation-delay:.15s}
.typing-dots span:nth-child(3){animation-delay:.3s}
@keyframes typeBounce{to{opacity:1;transform:translateY(-3px)}}
.typing-label{
  font-family:var(--font-mono);font-size:11px;color:var(--text-muted);
  margin-left:6px;
}

/* Input area */
.input-area{
  padding:16px 20px;background:var(--surface);
  border-top:1px solid var(--border);
  display:flex;gap:10px;flex-shrink:0;
  position:relative;z-index:10;
}
.input-area::before{
  content:'';position:absolute;top:-1px;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--amber-dim),transparent);
}
.input-wrap{
  flex:1;position:relative;display:flex;align-items:flex-end;
  background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);
  transition:border-color .2s,box-shadow .2s;
}
.input-wrap:focus-within{
  border-color:var(--amber);
  box-shadow:0 0 0 3px var(--amber-dim);
}
.input-wrap textarea{
  flex:1;background:transparent;border:none;
  padding:12px 14px;color:var(--text-bright);font-size:14px;
  font-family:var(--font-body);resize:none;outline:none;
  min-height:44px;max-height:160px;line-height:1.45;
}
.input-wrap textarea::placeholder{color:var(--text-dim)}
.send-btn{
  background:linear-gradient(135deg,var(--amber),#c88520);
  color:var(--bg);border:none;border-radius:var(--radius);
  padding:0 22px;height:44px;font-size:13px;font-weight:700;
  font-family:var(--font-mono);cursor:pointer;
  transition:all .2s;flex-shrink:0;
  text-transform:uppercase;letter-spacing:.5px;
}
.send-btn:hover{box-shadow:0 0 24px var(--amber-dim);transform:translateY(-1px)}
.send-btn:active{transform:translateY(0)}
.send-btn:disabled{opacity:.3;cursor:not-allowed;transform:none;box-shadow:none}

/* Welcome screen */
.welcome{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:80px 24px 40px;text-align:center;
  animation:welcomeFade .8s ease;
}
@keyframes welcomeFade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.welcome-logo{
  width:64px;height:64px;border-radius:16px;margin-bottom:28px;
  background:linear-gradient(135deg,var(--amber),#c88520);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--font-mono);font-weight:700;font-size:28px;color:var(--bg);
  box-shadow:0 0 60px var(--amber-dim),0 0 120px var(--amber-glow);
  position:relative;
}
.welcome-logo::before{
  content:'';position:absolute;inset:-4px;border-radius:20px;
  background:conic-gradient(from 0deg,var(--amber),transparent,var(--amber));
  opacity:.2;animation:logoSpin 8s linear infinite;
}
@keyframes logoSpin{to{transform:rotate(360deg)}}
.welcome h2{
  font-family:var(--font-mono);font-size:20px;font-weight:700;
  color:var(--text-bright);margin-bottom:10px;letter-spacing:-.3px;
}
.welcome p{
  font-size:14px;color:var(--text-muted);max-width:440px;line-height:1.6;
  margin-bottom:32px;
}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:520px}
.chip{
  background:var(--surface-2);border:1px solid var(--border);border-radius:8px;
  padding:10px 16px;font-size:12px;font-family:var(--font-mono);font-weight:500;
  cursor:pointer;transition:all .2s;color:var(--text);
  display:flex;align-items:center;gap:7px;
}
.chip:hover{border-color:var(--amber);color:var(--amber);background:var(--amber-dim)}
.chip .chip-icon{font-size:14px;opacity:.7}

/* Session bar */
.session-bar{
  padding:6px 20px;background:var(--bg);
  border-bottom:1px solid var(--border);
  font-family:var(--font-mono);font-size:10px;color:var(--text-dim);
  display:flex;align-items:center;gap:16px;flex-shrink:0;
}
.session-bar .sep{color:var(--border)}

/* Mobile */
@media(max-width:640px){
  .header{padding:0 14px;height:50px;gap:10px}
  .logo-mark{width:28px;height:28px;font-size:13px;border-radius:6px}
  .header-title{font-size:13px}
  .session-info{display:none}
  .chat{padding:16px 12px}
  .msg{padding:12px 14px;font-size:13px}
  .msg pre{padding:10px 12px}
  .input-area{padding:12px}
  .welcome{padding:50px 16px 30px}
  .welcome-logo{width:52px;height:52px;font-size:22px}
  .welcome h2{font-size:17px}
  .chips{gap:6px}
  .chip{padding:8px 12px;font-size:11px}
  .session-bar{padding:5px 14px;font-size:9px}
}
</style>
</head>
<body>

<div class="header">
  <div class="logo-mark">O</div>
  <div class="header-title">OVERSEER <span>/ personal assistant</span></div>
  <div class="header-right">
    <div class="session-info">
      <span id="sessionId">---</span>
      <span class="count" id="msgCount">0 msgs</span>
    </div>
    <div class="status-pill" id="statusPill">
      <span class="dot"></span>
      <span id="statusText">INIT</span>
    </div>
  </div>
</div>

<div class="session-bar" id="sessionBar">
  <span>MODEL: <span id="modelName">gemini-2.5-flash</span></span>
  <span class="sep">/</span>
  <span>SESSION: <span id="sessionDisplay">---</span></span>
  <span class="sep">/</span>
  <span>EDGE: cloudflare</span>
</div>

<div class="chat" id="chat">
  <div class="welcome" id="welcome">
    <div class="welcome-logo">O</div>
    <h2>OVERSEER</h2>
    <p>Your AI agency command interface. Connected to the OpenClaw gateway with 48 live tools — jobs, agents, costs, memory, deployments, and more.</p>
    <div class="chips">
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#9881;</span> Agency status</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#9733;</span> What's running?</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#36;</span> Cost summary</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128218;</span> Search memory</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128640;</span> Create a job</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128274;</span> List agents</div>
    </div>
  </div>
</div>

<div class="typing" id="typing">
  <div class="typing-dots"><span></span><span></span><span></span></div>
  <span class="typing-label" id="typingLabel">thinking...</span>
</div>

<div class="input-area">
  <div class="input-wrap">
    <textarea id="input" placeholder="Ask Overseer anything..." rows="1"></textarea>
  </div>
  <button class="send-btn" id="sendBtn" onclick="send()">SEND</button>
</div>

<script>
const $=id=>document.getElementById(id);
const chatEl=$('chat'),inputEl=$('input'),sendBtn=$('sendBtn');
const typingEl=$('typing'),welcomeEl=$('welcome');
const statusPill=$('statusPill'),statusText=$('statusText');
const typingLabel=$('typingLabel');
const sessionDisplay=$('sessionDisplay'),msgCountEl=$('msgCount'),sessionIdEl=$('sessionId');
const modelNameEl=$('modelName');

let sessionKey=localStorage.getItem('oc_session');
if(!sessionKey){sessionKey='web:'+crypto.randomUUID();localStorage.setItem('oc_session',sessionKey)}
sessionDisplay.textContent=sessionKey.slice(0,12)+'...';
sessionIdEl.textContent=sessionKey.slice(4,12);
let totalMsgs=0;

inputEl.addEventListener('input',()=>{
  inputEl.style.height='auto';
  inputEl.style.height=Math.min(inputEl.scrollHeight,160)+'px';
});
inputEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}
});

function sendChip(el){inputEl.value=el.textContent.replace(/^[^\\w]+/,'').trim();send()}

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function renderMd(text){
  // Code blocks with language tags
  text=text.replace(/\`\`\`(\\w*?)\\n([\\s\\S]*?)\`\`\`/g,(_,lang,code)=>{
    const tag=lang?'<span class="lang-tag">'+esc(lang)+'</span>':'';
    return '<pre>'+tag+'<code>'+esc(code.trim())+'</code></pre>';
  });
  // Inline code
  text=text.replace(/\`([^\`]+)\`/g,(_,c)=>'<code>'+esc(c)+'</code>');
  // Headers
  text=text.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  text=text.replace(/^## (.+)$/gm,'<h2>$1</h2>');
  text=text.replace(/^# (.+)$/gm,'<h1>$1</h1>');
  // Bold & italic
  text=text.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g,'<strong><em>$1</em></strong>');
  text=text.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  text=text.replace(/\\*(.+?)\\*/g,'<em>$1</em>');
  // Links
  text=text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Blockquotes
  text=text.replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>');
  // Horizontal rules
  text=text.replace(/^---$/gm,'<hr>');
  // Unordered lists
  text=text.replace(/^[\\-\\*] (.+)$/gm,'<li>$1</li>');
  text=text.replace(/(<li>.*<\\/li>)/gs,m=>'<ul>'+m+'</ul>');
  text=text.replace(/<\\/ul>\\s*<ul>/g,'');
  // Ordered lists
  text=text.replace(/^\\d+\\. (.+)$/gm,'<li>$1</li>');
  // Tables
  text=text.replace(/^\\|(.+)\\|$/gm,(_,row)=>{
    const cells=row.split('|').map(c=>c.trim());
    return '<tr>'+cells.map(c=>'<td>'+c+'</td>').join('')+'</tr>';
  });
  text=text.replace(/(<tr>.*<\\/tr>)/gs,m=>{
    let rows=m;
    // Convert separator row to nothing, first row to th
    rows=rows.replace(/<tr><td>[-:\\s|]+<\\/td>(<td>[-:\\s|]+<\\/td>)*<\\/tr>/g,'');
    rows=rows.replace(/<tr>(.*?)<\\/tr>/,(_, r)=>'<thead><tr>'+r.replace(/<td>/g,'<th>').replace(/<\\/td>/g,'</th>')+'</tr></thead>');
    return '<table>'+rows+'</table>';
  });
  // Paragraphs (lines not already wrapped)
  text=text.replace(/^(?!<[hupoltbr])(\\S.+)$/gm,'<p>$1</p>');
  return text;
}

const TOOL_CATEGORIES={
  list_jobs:'jobs',create_job:'jobs',get_job:'jobs',kill_job:'jobs',approve_job:'jobs',
  get_cost_summary:'costs',
  get_agency_status:'system',get_runner_status:'system',get_events:'system',
  list_agents:'agents',spawn_agent:'agents',
  search_memory:'memory',save_memory:'memory',get_reflections:'memory',
  list_proposals:'jobs',create_proposal:'jobs',
  github_repo_info:'github',github_create_issue:'github',
  web_search:'system',web_fetch:'system',web_scrape:'system',research_task:'system',perplexity_research:'system',
  send_chat_to_gateway:'agents',
  get_gmail_inbox:'system',get_calendar_today:'system',create_calendar_event:'system',get_calendar_upcoming:'system',list_calendars:'system',trash_emails:'system',label_emails:'system',send_email:'system',get_gmail_labels:'system',
  shell_execute:'system',git_operations:'github',
  vercel_deploy:'system',
  file_read:'system',file_write:'system',file_edit:'system',
  glob_files:'system',grep_search:'system',
  compute_sort:'system',compute_stats:'system',compute_math:'system',
  compute_search:'system',compute_matrix:'system',compute_prime:'system',
  compute_hash:'system',compute_convert:'system',
  send_slack_message:'system',security_scan:'system',
  prediction_market:'system',polymarket_prices:'system',polymarket_monitor:'system',polymarket_portfolio:'system',env_manage:'system',
  process_manage:'system',install_package:'system',
  get_weather:'system',get_crypto_prices:'system',nutrition_lookup:'system',
};
const TOOL_ICONS={
  jobs:'&#9654;',costs:'&#36;',agents:'&#9881;',
  memory:'&#128218;',github:'&#128025;',system:'&#9881;',
};
const TOOL_LABELS={
  list_jobs:'JOBS',create_job:'CREATE JOB',get_job:'JOB',kill_job:'KILL JOB',
  approve_job:'APPROVE',get_cost_summary:'COSTS',get_agency_status:'STATUS',
  get_runner_status:'RUNNER',get_events:'EVENTS',list_agents:'AGENTS',
  spawn_agent:'SPAWN',search_memory:'MEMORY',save_memory:'SAVE MEM',
  get_reflections:'REFLECT',list_proposals:'PROPOSALS',create_proposal:'PROPOSAL',
  github_repo_info:'GITHUB',github_create_issue:'NEW ISSUE',
  web_search:'SEARCH',web_fetch:'FETCH',web_scrape:'SCRAPE',
  research_task:'RESEARCH',perplexity_research:'PERPLEXITY',send_chat_to_gateway:'DELEGATE',
  get_gmail_inbox:'GMAIL',get_calendar_today:'CALENDAR',create_calendar_event:'CALENDAR',get_calendar_upcoming:'CALENDAR',list_calendars:'CALENDAR',trash_emails:'GMAIL',label_emails:'GMAIL',send_email:'GMAIL',get_gmail_labels:'GMAIL',
  shell_execute:'SHELL',git_operations:'GIT',vercel_deploy:'DEPLOY',
  file_read:'FILE',file_write:'WRITE',file_edit:'EDIT',
  glob_files:'GLOB',grep_search:'GREP',
  send_slack_message:'SLACK',security_scan:'SECURITY',
  prediction_market:'MARKETS',polymarket_prices:'PRICES',polymarket_monitor:'MONITOR',polymarket_portfolio:'PORTFOLIO',env_manage:'ENV',
  process_manage:'PROCESS',install_package:'INSTALL',
  get_weather:'WEATHER',get_crypto_prices:'CRYPTO',nutrition_lookup:'NUTRITION',
};

function toolBadgeHtml(toolName){
  if(!toolName)return '';
  const cat=TOOL_CATEGORIES[toolName]||'system';
  const icon=TOOL_ICONS[cat]||'&#9881;';
  const label=TOOL_LABELS[toolName]||toolName.toUpperCase().replace(/_/g,' ');
  return '<div class="tool-badge '+cat+'"><span class="tool-icon">'+icon+'</span>'+label+'</div>';
}

function addMsg(role,text,meta){
  if(welcomeEl)welcomeEl.style.display='none';
  const group=document.createElement('div');
  group.className='msg-group '+role;
  const label=document.createElement('div');
  label.className='msg-label';
  label.textContent=role==='user'?'YOU':'OVERSEER';
  group.appendChild(label);
  const bubble=document.createElement('div');
  bubble.className='msg';
  let content='';
  if(role==='bot'&&meta&&meta.tool_used){
    content+=toolBadgeHtml(meta.tool_used);
  }
  content+=renderMd(text);
  bubble.innerHTML=content;
  group.appendChild(bubble);
  chatEl.appendChild(group);
  chatEl.scrollTop=chatEl.scrollHeight;
  totalMsgs++;
  msgCountEl.textContent=totalMsgs+' msgs';
}

let sending=false;
async function send(){
  const text=inputEl.value.trim();
  if(!text||sending)return;
  sending=true;sendBtn.disabled=true;
  inputEl.value='';inputEl.style.height='auto';
  addMsg('user',text);
  typingLabel.textContent='thinking...';
  typingEl.classList.add('show');
  chatEl.appendChild(typingEl);
  chatEl.scrollTop=chatEl.scrollHeight;

  try{
    const resp=await fetch('/api/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,sessionKey})
    });
    const data=await resp.json();
    if(data.sessionKey){sessionKey=data.sessionKey;localStorage.setItem('oc_session',sessionKey)}
    if(data.model)modelNameEl.textContent=data.model;
    if(data.sessionMessageCount)msgCountEl.textContent=data.sessionMessageCount+' in session';
    if(data.tool_used)typingLabel.textContent='called '+data.tool_used+'...';
    const reply=data.response||data.message||data.reply||data.error||'No response';
    addMsg('bot',reply,{tool_used:data.tool_used});
  }catch(err){
    addMsg('bot','Connection error: '+err.message,{});
  }finally{
    typingEl.classList.remove('show');
    sending=false;sendBtn.disabled=false;inputEl.focus();
  }
}

// Health check
(async()=>{
  try{
    const r=await fetch('/health');
    const d=await r.json();
    if(d.gateway==='ok'){
      statusText.textContent='ONLINE';
      statusPill.className='status-pill';
    }else{
      statusText.textContent='DEGRADED';
      statusPill.className='status-pill degraded';
    }
  }catch{
    statusText.textContent='OFFLINE';
    statusPill.className='status-pill offline';
  }
})();

inputEl.focus();
</script>
</body>
</html>`;

// ---------------------------------------------------------------------------
// WebSocket proxy at /ws
// ---------------------------------------------------------------------------
// Cloudflare Workers handle WebSocket upgrades via the fetch handler
// returning a WebSocket pair. We create a pair, connect to the upstream
// VPS gateway WebSocket, and relay frames in both directions.

async function handleWebSocket(request: Request, env: Env): Promise<Response> {
  // Derive upstream WS URL from GATEWAY_URL (http(s):// -> ws(s)://)
  const gwUrl = env.GATEWAY_URL.replace(/^http/, "ws");
  const upstreamUrl = `${gwUrl}/ws`;

  // Create the client<->worker pair
  const [client, server] = Object.values(new WebSocketPair());

  // Accept the server side so we can send/receive
  server.accept();

  // Connect to upstream VPS gateway WebSocket
  let upstream: WebSocket | null = null;
  try {
    const upstreamResp = await fetch(upstreamUrl, {
      headers: {
        Upgrade: "websocket",
        "X-Auth-Token": env.GATEWAY_TOKEN,
      },
    });
    upstream = upstreamResp.webSocket;
    if (!upstream) {
      server.send(
        JSON.stringify({
          error: "upstream_ws_unavailable",
          detail: "Gateway did not return a WebSocket",
        }),
      );
      server.close(1011, "Upstream unavailable");
      return new Response(null, { status: 101, webSocket: client });
    }
    upstream.accept();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    server.send(JSON.stringify({ error: "upstream_connect_failed", detail: msg }));
    server.close(1011, "Upstream connect failed");
    return new Response(null, { status: 101, webSocket: client });
  }

  // Relay: client -> upstream
  server.addEventListener("message", (evt) => {
    try {
      if (upstream && upstream.readyState === WebSocket.READY_STATE_OPEN) {
        upstream.send(typeof evt.data === "string" ? evt.data : evt.data);
      }
    } catch {
      // upstream gone
    }
  });

  server.addEventListener("close", (evt) => {
    try {
      upstream?.close(evt.code, evt.reason);
    } catch {
      // ignore
    }
  });

  // Relay: upstream -> client
  upstream.addEventListener("message", (evt) => {
    try {
      if (server.readyState === WebSocket.READY_STATE_OPEN) {
        server.send(typeof evt.data === "string" ? evt.data : evt.data);
      }
    } catch {
      // client gone
    }
  });

  upstream.addEventListener("close", (evt) => {
    try {
      server.close(evt.code, evt.reason);
    } catch {
      // ignore
    }
  });

  upstream.addEventListener("error", () => {
    try {
      server.close(1011, "Upstream error");
    } catch {
      // ignore
    }
  });

  return new Response(null, { status: 101, webSocket: client });
}

// ---------------------------------------------------------------------------
// Scheduled handler — cron-triggered reminder checks + morning briefing
// ---------------------------------------------------------------------------

async function sendTelegramMessage(env: Env, text: string) {
  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
  const chatId = (env.TELEGRAM_OWNER_ID || "").trim();
  if (!chatId) return;

  const resp = await fetch(`${tgApi}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "HTML",
    }),
  });

  // If HTML parsing fails, retry without formatting
  if (!resp.ok) {
    await fetch(`${tgApi}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
  }
}

async function handleScheduled(env: Env, scheduledTime: number) {
  const hour = new Date(scheduledTime).getUTCHours();

  // 1. Check for due reminders (runs every 15 min)
  try {
    const remindersResp = await gatewayFetch(env, "/api/reminders/due");
    if (remindersResp.ok) {
      const data = (await remindersResp.json()) as {
        reminders?: Array<{ id: string; content: string; tags?: string[] }>;
      };
      const reminders = data.reminders || [];
      for (const reminder of reminders) {
        await sendTelegramMessage(env, `<b>Reminder</b>\n${reminder.content}`);
        // Mark as reminded so it doesn't fire again
        await gatewayFetch(env, "/api/reminders/mark", {
          method: "POST",
          body: JSON.stringify({ memory_id: reminder.id }),
        });
      }
    }
  } catch {
    // Don't crash the cron if reminders fail
  }

  // 2. Morning briefing at 14:00 UTC (7am MST) — Tue-Sun only (Miles is OFF Monday)
  if (hour === 14) {
    const day = new Date(scheduledTime).getUTCDay(); // 0=Sun, 1=Mon
    if (day === 1) return; // Monday OFF — skip briefing

    try {
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      const dayName = dayNames[day];
      let briefing = `<b>Good morning Miles!</b> Happy ${dayName}.\n\n`;

      // --- Weather ---
      try {
        const wxUrl = "https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=1&timezone=America%2FPhoenix";
        const wxResp = await fetch(wxUrl);
        if (wxResp.ok) {
          const wx = (await wxResp.json()) as {
            current?: { temperature_2m?: number; weather_code?: number };
            daily?: { temperature_2m_max?: number[]; temperature_2m_min?: number[]; precipitation_probability_max?: number[] };
          };
          const wxCodes: Record<number, string> = { 0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast", 45: "Foggy", 51: "Light Drizzle", 61: "Light Rain", 63: "Rain", 65: "Heavy Rain", 71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 80: "Rain Showers", 95: "Thunderstorm" };
          const temp = wx.current?.temperature_2m;
          const hi = wx.daily?.temperature_2m_max?.[0];
          const lo = wx.daily?.temperature_2m_min?.[0];
          const rainPct = wx.daily?.precipitation_probability_max?.[0] || 0;
          const cond = wxCodes[wx.current?.weather_code || 0] || "Unknown";
          briefing += `<b>Weather:</b> ${cond}, ${temp}°F (High ${hi}° / Low ${lo}°)`;
          if (rainPct > 20) briefing += ` — ${rainPct}% chance of rain`;
          briefing += "\n\n";
        }
      } catch { /* weather non-critical */ }

      // --- Habit streaks ---
      try {
        const KV = env.KV_CACHE;
        const today = new Date().toISOString().split("T")[0];
        const habitsRaw = await KV.get("lifeos:habits");
        const habits: Record<string, { description?: string }> = habitsRaw
          ? JSON.parse(habitsRaw)
          : { water_8cups: {}, sleep_8hrs: {}, workout: {}, stretch: {}, healthy_meal: {} };

        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const todayLog = logRaw ? JSON.parse(logRaw) : {};
        const habitNames = Object.keys(habits);
        const done = habitNames.filter((h) => todayLog[h]?.done).length;

        // Get yesterday's completion for streak context
        const yesterday = new Date(Date.now() - 86400000).toISOString().split("T")[0];
        const yLogRaw = await KV.get(`lifeos:habit_log:${yesterday}`);
        const yLog = yLogRaw ? JSON.parse(yLogRaw) : {};
        const yDone = habitNames.filter((h) => yLog[h]?.done).length;

        briefing += `<b>Habits:</b> ${done}/${habitNames.length} done today`;
        if (yDone > 0) briefing += ` (yesterday: ${yDone}/${habitNames.length})`;
        briefing += "\n";
        for (const h of habitNames) {
          briefing += `  ${todayLog[h]?.done ? "✅" : "⬜"} ${h.replace(/_/g, " ")}\n`;
        }
        briefing += "\n";
      } catch { /* habits non-critical */ }

      // --- Cost summary ---
      try {
        const costResp = await gatewayFetch(env, "/api/costs/summary");
        if (costResp.ok) {
          const costs = (await costResp.json()) as {
            today?: number; this_month?: number; budget_remaining?: number;
          };
          if (costs.today !== undefined) {
            briefing += `<b>Costs:</b> $${(costs.today || 0).toFixed(2)} today, $${(costs.this_month || 0).toFixed(2)} this month\n\n`;
          }
        }
      } catch { /* costs non-critical */ }

      // --- Day plan ---
      try {
        const dayPlanResp = await gatewayFetch(env, "/api/plan-my-day", {
          method: "POST",
          body: JSON.stringify({ focus: "all" }),
        });
        if (dayPlanResp.ok) {
          const plan = (await dayPlanResp.json()) as { plan?: string };
          if (plan.plan) {
            briefing += plan.plan.substring(0, 1200) + "\n\n";
          }
        }
      } catch { /* plan non-critical */ }

      // --- Smart context suggestions ---
      if (day === 1) { // Monday — OFF work, maybe soccer
        briefing += "<b>Monday OFF!</b> Great day for big tasks, studying, or soccer if it's on this week.\n\n";
      }

      // --- Pending reminders ---
      try {
        const memResp = await gatewayFetch(env, "/api/memories?tag=reminder&limit=5");
        if (memResp.ok) {
          const memData = (await memResp.json()) as {
            memories?: Array<{ content: string; remind_at?: string; reminded?: boolean }>;
          };
          const pending = (memData.memories || []).filter((m) => m.remind_at && !m.reminded);
          if (pending.length > 0) {
            briefing += "<b>Reminders:</b>\n";
            for (const p of pending) {
              briefing += `- ${p.content}\n`;
            }
            briefing += "\n";
          }
        }
      } catch { /* reminders non-critical */ }

      // --- Motivation quote ---
      const quotes = [
        "The best time to plant a tree was 20 years ago. The second best time is now.",
        "Ship it, then fix it. Perfect is the enemy of done.",
        "You built more in 2 months than most build in a year. Keep going.",
        "Small daily improvements lead to staggering long-term results.",
        "The only way to do great work is to love what you do. — Steve Jobs",
        "Move fast and build things. You're not just learning — you're creating.",
        "Every expert was once a beginner. Every pro was once an amateur.",
        "Success is the sum of small efforts, repeated day in and day out.",
        "Your AI system costs $5/month. Companies pay $50K for the same thing. That's your edge.",
        "Code is the new literacy. You're already fluent.",
        "The gap between where you are and where you want to be is called consistency.",
        "Don't wait for the perfect moment. Take the moment and make it perfect.",
      ];
      const quoteIdx = Math.floor(Date.now() / 86400000) % quotes.length;
      briefing += `<i>"${quotes[quoteIdx]}"</i>\n\nLet's have a great day! 💪`;

      await sendTelegramMessage(env, briefing);
    } catch {
      // Don't crash the cron
    }
  }

  // 3. Auto-log predictions at 21:00 UTC (2pm MST) — before NBA games start
  if (hour === 21) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 1) return; // Monday OFF

    try {
      const logResp = await gatewayFetch(env, "/api/sports/tracker", {
        method: "POST",
        body: JSON.stringify({ action: "log", bankroll: 100 }),
      });
      if (logResp.ok) {
        const logData = (await logResp.json()) as { games?: number; bets?: number; date?: string };
        if (logData.games && logData.games > 0) {
          await sendTelegramMessage(
            env,
            `<b>Predictions logged</b>\n${logData.games} games, ${logData.bets || 0} bets saved for ${logData.date || "today"}`,
          );
        }
      }
    } catch {
      // Don't crash the cron
    }
  }

  // 4. Auto-grade yesterday at 17:00 UTC (10am MST) — after games finished
  if (hour === 17) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 1) return; // Monday OFF (and no Sunday games to grade typically)

    try {
      const checkResp = await gatewayFetch(env, "/api/sports/tracker", {
        method: "POST",
        body: JSON.stringify({ action: "yesterday" }),
      });
      if (checkResp.ok) {
        const checkData = (await checkResp.json()) as {
          summary?: {
            picks_correct?: number;
            picks_total?: number;
            picks_pct?: number;
            total_profit?: number;
            roi_pct?: number;
          };
          date?: string;
        };
        const s = checkData.summary;
        if (s && s.picks_total && s.picks_total > 0) {
          const profitSign = (s.total_profit || 0) >= 0 ? "+" : "";
          await sendTelegramMessage(
            env,
            `<b>Yesterday's results</b> (${checkData.date})\nPicks: ${s.picks_correct}/${s.picks_total} (${s.picks_pct}%)\nProfit: ${profitSign}$${(s.total_profit || 0).toFixed(2)} (${profitSign}${s.roi_pct}% ROI)`,
          );
        }
      }
    } catch {
      // Don't crash the cron
    }
  }

  // 5. Evening summary at 05:00 UTC (10pm MST) — end-of-day review
  if (hour === 5) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 2) return; // Monday night (Tue UTC) — skip, Miles is OFF Monday

    try {
      let summary = "<b>Evening Summary</b>\n\n";

      // --- Habit completion ---
      try {
        const KV = env.KV_CACHE;
        const today = new Date().toISOString().split("T")[0];
        const habitsRaw = await KV.get("lifeos:habits");
        const habits: Record<string, unknown> = habitsRaw
          ? JSON.parse(habitsRaw)
          : { water_8cups: {}, sleep_8hrs: {}, workout: {}, stretch: {}, healthy_meal: {} };
        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const todayLog: Record<string, { done?: boolean }> = logRaw ? JSON.parse(logRaw) : {};
        const habitNames = Object.keys(habits);
        const done = habitNames.filter((h) => todayLog[h]?.done).length;

        if (done === habitNames.length && habitNames.length > 0) {
          summary += `<b>Habits:</b> ${done}/${habitNames.length} — Perfect day! 🔥\n`;
        } else {
          summary += `<b>Habits:</b> ${done}/${habitNames.length} completed\n`;
          const missed = habitNames.filter((h) => !todayLog[h]?.done);
          if (missed.length > 0) {
            summary += `Missed: ${missed.map((h) => h.replace(/_/g, " ")).join(", ")}\n`;
          }
        }
        summary += "\n";
      } catch { /* non-critical */ }

      // --- Cost summary ---
      try {
        const costResp = await gatewayFetch(env, "/api/costs/summary");
        if (costResp.ok) {
          const costs = (await costResp.json()) as {
            today?: number; this_month?: number; jobs_today?: number;
          };
          summary += `<b>Today's costs:</b> $${(costs.today || 0).toFixed(2)} across ${costs.jobs_today || 0} job(s)\n`;
          summary += `<b>Month total:</b> $${(costs.this_month || 0).toFixed(2)}\n\n`;
        }
      } catch { /* non-critical */ }

      // --- Agency status ---
      try {
        const statusResp = await gatewayFetch(env, "/api/agency/status");
        if (statusResp.ok) {
          const status = (await statusResp.json()) as {
            active_jobs?: number; completed_today?: number; failed_today?: number;
          };
          if (status.completed_today || status.failed_today) {
            summary += `<b>Jobs:</b> ${status.completed_today || 0} completed, ${status.failed_today || 0} failed\n\n`;
          }
        }
      } catch { /* non-critical */ }

      // --- Tomorrow preview ---
      const tomorrow = new Date(scheduledTime + 86400000);
      const tDay = tomorrow.getUTCDay();
      if (tDay === 1) {
        summary += "<b>Tomorrow:</b> Monday — day OFF! Rest up. 🛌\n";
      } else {
        const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
        summary += `<b>Tomorrow:</b> ${dayNames[tDay]} — work shift 5pm-10pm\n`;
      }

      summary += "\nGood night! 🌙";
      await sendTelegramMessage(env, summary);
    } catch {
      // Don't crash the cron
    }
  }

  // 6. Sunday Weekly Planner at 15:00 UTC (8am MST) — plan the whole week
  if (hour === 15) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day !== 0) return; // Only runs on Sunday

    try {
      // Fetch the full week: calendar, deadlines, reminders
      const [calWeekRes, memoriesRes, costRes] = await Promise.all([
        gatewayFetch(env, "/api/calendar/upcoming?days=7")
          .then((r) => r.json())
          .catch(() => ({ events: [] })),
        gatewayFetch(env, "/api/memories?tag=reminder&limit=20")
          .then((r) => r.json())
          .catch(() => ({ memories: [] })),
        gatewayFetch(env, "/api/costs/summary")
          .then((r) => r.json())
          .catch(() => ({})),
      ]);

      const events = (calWeekRes as { events?: Array<{ summary?: string; start?: { dateTime?: string; date?: string }; end?: { dateTime?: string; date?: string } }> }).events || [];
      const memories = ((memoriesRes as { memories?: Array<{ content: string; remind_at?: string }> }).memories || []);

      let plan = "<b>Weekly Plan — Sunday Prep</b>\n\n";

      // Group events by day
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      const weekDays: Record<string, Array<{ time: string; title: string }>> = {};

      for (const ev of events) {
        const startStr = ev.start?.dateTime || ev.start?.date || "";
        const d = new Date(startStr);
        const dayKey = dayNames[d.getDay()] || "Unknown";
        if (!weekDays[dayKey]) weekDays[dayKey] = [];
        const timeStr = ev.start?.dateTime
          ? d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/Phoenix" })
          : "All day";
        weekDays[dayKey].push({ time: timeStr, title: ev.summary || "Event" });
      }

      // Build day-by-day plan
      const orderedDays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      for (const dayName of orderedDays) {
        const dayEvents = weekDays[dayName] || [];
        const isOff = dayName === "Monday";

        plan += `<b>${dayName}</b>`;
        if (isOff) plan += " (OFF work)";
        else if (dayName !== "Sunday") plan += " (work 5-10pm)";
        plan += "\n";

        if (dayEvents.length > 0) {
          for (const ev of dayEvents) {
            plan += `  ${ev.time} — ${ev.title}\n`;
          }
        } else {
          plan += "  No calendar events\n";
        }

        // Add free time suggestion
        if (!isOff && dayName !== "Sunday") {
          plan += "  Free blocks: morning + afternoon (before 5pm)\n";
        } else if (isOff) {
          plan += "  Full day free — big tasks, projects, soccer?\n";
        }
        plan += "\n";
      }

      // Upcoming deadlines from reminders
      const upcomingReminders = memories.filter((m) => m.remind_at);
      if (upcomingReminders.length > 0) {
        plan += "<b>Deadlines & Reminders:</b>\n";
        for (const r of upcomingReminders.slice(0, 10)) {
          const when = r.remind_at ? new Date(r.remind_at).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "America/Phoenix" }) : "";
          plan += `  ${when} — ${r.content}\n`;
        }
        plan += "\n";
      }

      // Cost context
      const costs = costRes as { this_month?: number; budget_remaining?: number };
      if (costs.this_month !== undefined) {
        plan += `<b>Budget:</b> $${(costs.this_month || 0).toFixed(2)} spent this month\n\n`;
      }

      plan += "Tell me if you want to adjust anything! I'll send daily plans each morning with specific time blocks.";

      await sendTelegramMessage(env, plan);
    } catch {
      // Don't crash the cron
    }
  }

  // 7. Work shift start at 00:00 UTC (5pm MST) — quick status check
  if (hour === 0) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 1) return; // Monday OFF

    try {
      const statusResp = await gatewayFetch(env, "/api/agency/status");
      if (statusResp.ok) {
        const status = (await statusResp.json()) as {
          active_jobs?: number;
          pending_jobs?: number;
          alerts?: string[];
        };
        const active = status.active_jobs || 0;
        const pending = status.pending_jobs || 0;
        const alerts = status.alerts || [];

        // Only send if there's something worth mentioning
        if (active > 0 || pending > 0 || alerts.length > 0) {
          let msg = "<b>Work shift starting</b>\n";
          if (active > 0) msg += `${active} active job(s)\n`;
          if (pending > 0) msg += `${pending} pending job(s)\n`;
          if (alerts.length > 0) msg += `\nAlerts: ${alerts.join(", ")}`;
          await sendTelegramMessage(env, msg);
        }
      }
    } catch {
      // Don't crash
    }
  }
}

// ---------------------------------------------------------------------------
// Export — use object syntax so we can intercept WebSocket upgrades + cron
// ---------------------------------------------------------------------------
export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // WebSocket upgrade at /ws
    if (url.pathname === "/ws" && request.headers.get("Upgrade") === "websocket") {
      return handleWebSocket(request, env);
    }

    // Everything else goes through Hono
    return app.fetch(request, env, ctx);
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(handleScheduled(env, event.scheduledTime));
  },
};
