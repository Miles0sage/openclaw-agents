/**
 * OpenClaw Personal Assistant Worker
 *
 * A clean, lightweight personal assistant for Miles.
 * ~28 personal life tools only — NO dev tools, NO trading, NO code ops.
 *
 * LLM: DeepSeek V3 via OpenAI-compatible API with tool calling.
 * Storage: D1 (memory), KV (sessions, Life OS data).
 * Crons: Morning briefing, evening summary, weekly planner, reminder checks.
 */

import { Hono } from "hono";
import { cors } from "hono/cors";
import { extractAndStore, getMemoryContext } from "./extraction";
import { initializeMemoryTables } from "./memory";
import {
  initializeCourseTables,
  createCourse,
  listCourses,
  getLesson,
  getCourseLessons,
  getNextLesson,
  submitQuiz,
  getCourseProgress,
  deleteCourse,
  getFlashcardsForReview,
  reviewFlashcard,
  getFlashcardStats,
} from "./coursemaker";
import {
  initializeAnalyticsTables,
  logLLMCall,
  getCostSummary,
  getRecentCalls,
} from "./analytics";
import {
  initializeGraphTables,
  linkMemoryToEntities,
  getEntityGraph,
  getRelatedMemories,
  getGraphStats,
} from "./knowledge-graph";
import {
  createPodcast,
  sendTelegramAudioResult,
} from "./podcast";
import type { PodcastRequest } from "./podcast";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Env {
  GATEWAY_URL: string;
  GATEWAY_TOKEN: string;
  BEARER_TOKEN?: string;
  ENVIRONMENT: string;
  RATE_LIMIT_PER_MINUTE: string;
  DEEPSEEK_API_KEY: string;
  GEMINI_API_KEY?: string;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_OWNER_ID: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  NOTION_TOKEN?: string;
  NOTION_AGENDA_PAGE?: string;
  NOTION_INBOX_PAGE?: string;
  NOTION_NOTES_PAGE?: string;
  NOTION_TASKS_DB?: string;
  OUTLOOK_ICS_MAIN?: string;
  OUTLOOK_ICS_WORK?: string;
  DB: D1Database;
  KV_CACHE: KVNamespace;
  KV_SESSIONS: KVNamespace;
}

interface SessionData {
  messages: Array<{ role: string; content: string; timestamp: string }>;
  created: string;
  updated: string;
  messageCount: number;
}

// ---------------------------------------------------------------------------
// Outlook ICS calendar parser
// ---------------------------------------------------------------------------

interface CalEvent {
  summary: string;
  start: string;
  end: string;
  location: string;
  allDay: boolean;
  calendar: string;
}

function parseICS(icsText: string, calName: string): CalEvent[] {
  const events: CalEvent[] = [];
  const blocks = icsText.split("BEGIN:VEVENT");
  for (let i = 1; i < blocks.length; i++) {
    const block = blocks[i].split("END:VEVENT")[0];
    const lines = block.replace(/\r\n /g, "").split(/\r?\n/);
    let summary = "", start = "", end = "", location = "", allDay = false;
    for (const line of lines) {
      if (line.startsWith("SUMMARY:")) summary = line.slice(8);
      else if (line.startsWith("LOCATION:")) location = line.slice(9);
      else if (line.startsWith("DTSTART")) {
        const val = line.includes(":") ? line.split(":").pop()! : "";
        start = val;
        if (line.includes("VALUE=DATE") && !line.includes("VALUE=DATE-TIME")) allDay = true;
      } else if (line.startsWith("DTEND")) {
        end = line.includes(":") ? line.split(":").pop()! : "";
      }
    }
    if (summary && start) {
      events.push({ summary, start, end, location, allDay, calendar: calName });
    }
  }
  return events;
}

function formatICSDate(d: string): string {
  if (d.length < 8) return d;
  const y = d.slice(0, 4), m = d.slice(4, 6), day = d.slice(6, 8);
  if (d.length >= 13) {
    const h = parseInt(d.slice(9, 11)), min = d.slice(11, 13);
    const ampm = h >= 12 ? "PM" : "AM";
    const h12 = h > 12 ? h - 12 : h === 0 ? 12 : h;
    return `${y}-${m}-${day} ${h12}:${min}${ampm}`;
  }
  return `${y}-${m}-${day}`;
}

async function getOutlookEvents(env: Env, daysAhead: number = 14): Promise<string> {
  const feeds: { url: string; name: string }[] = [];
  if (env.OUTLOOK_ICS_MAIN) feeds.push({ url: env.OUTLOOK_ICS_MAIN, name: "NAU Calendar" });
  if (env.OUTLOOK_ICS_WORK) feeds.push({ url: env.OUTLOOK_ICS_WORK, name: "PDC Student Worker" });
  if (feeds.length === 0) return "No Outlook calendars configured.";

  const now = new Date();
  const todayStr = now.toISOString().slice(0, 10).replace(/-/g, "");
  const cutoff = new Date(now.getTime() + daysAhead * 86400000);
  const cutoffStr = cutoff.toISOString().slice(0, 10).replace(/-/g, "");

  let allEvents: CalEvent[] = [];
  for (const feed of feeds) {
    try {
      const resp = await fetch(feed.url);
      const text = await resp.text();
      const events = parseICS(text, feed.name);
      allEvents = allEvents.concat(events);
    } catch (e) {
      allEvents.push({ summary: `Error fetching ${feed.name}`, start: todayStr, end: "", location: "", allDay: true, calendar: feed.name });
    }
  }

  // Filter to date range
  const upcoming = allEvents.filter((ev) => {
    const evDate = ev.start.slice(0, 8);
    return evDate >= todayStr && evDate <= cutoffStr;
  });

  // Sort by start date
  upcoming.sort((a, b) => a.start.localeCompare(b.start));

  if (upcoming.length === 0) return `No Outlook events in the next ${daysAhead} days.`;

  let out = `Outlook Calendar — next ${daysAhead} days (${upcoming.length} events):\n\n`;
  for (const ev of upcoming) {
    const time = formatICSDate(ev.start);
    const loc = ev.location ? ` @ ${ev.location}` : "";
    const cal = ev.calendar !== "NAU Calendar" ? ` [${ev.calendar}]` : "";
    out += `• ${time} — ${ev.summary}${loc}${cal}\n`;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Notion helpers
// ---------------------------------------------------------------------------

async function notionAppendBlock(env: Env, pageId: string, text: string, title?: string) {
  if (!env.NOTION_TOKEN || !pageId) return;
  const children: Record<string, unknown>[] = [];
  if (title) {
    children.push({
      object: "block",
      type: "heading_2",
      heading_2: { rich_text: [{ text: { content: title } }] },
    });
  }
  // Split text into chunks of 2000 chars (Notion limit per block)
  const lines = text.split("\n");
  let chunk = "";
  for (const line of lines) {
    if ((chunk + "\n" + line).length > 1900) {
      children.push({
        object: "block",
        type: "paragraph",
        paragraph: { rich_text: [{ text: { content: chunk } }] },
      });
      chunk = line;
    } else {
      chunk = chunk ? chunk + "\n" + line : line;
    }
  }
  if (chunk) {
    children.push({
      object: "block",
      type: "paragraph",
      paragraph: { rich_text: [{ text: { content: chunk } }] },
    });
  }
  children.push({ object: "block", type: "divider", divider: {} });

  await fetch(`https://api.notion.com/v1/blocks/${pageId}/children`, {
    method: "PATCH",
    headers: {
      "Authorization": `Bearer ${env.NOTION_TOKEN}`,
      "Notion-Version": "2022-06-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ children }),
  });
}

async function notionCreatePage(env: Env, parentPageId: string, title: string, content: string) {
  if (!env.NOTION_TOKEN || !parentPageId) return;
  const children: Record<string, unknown>[] = [];
  const lines = content.split("\n");
  let chunk = "";
  for (const line of lines) {
    if ((chunk + "\n" + line).length > 1900) {
      children.push({
        object: "block",
        type: "paragraph",
        paragraph: { rich_text: [{ text: { content: chunk } }] },
      });
      chunk = line;
    } else {
      chunk = chunk ? chunk + "\n" + line : line;
    }
  }
  if (chunk) {
    children.push({
      object: "block",
      type: "paragraph",
      paragraph: { rich_text: [{ text: { content: chunk } }] },
    });
  }

  await fetch("https://api.notion.com/v1/pages", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.NOTION_TOKEN}`,
      "Notion-Version": "2022-06-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      parent: { page_id: parentPageId },
      properties: { title: { title: [{ text: { content: title } }] } },
      children,
    }),
  });
}

async function notionAddTask(env: Env, task: string, area?: string, priority?: string, dueDate?: string) {
  if (!env.NOTION_TOKEN || !env.NOTION_TASKS_DB) return;
  const properties: Record<string, unknown> = {
    Task: { title: [{ text: { content: task } }] },
    Status: { select: { name: "To Do" } },
    Source: { select: { name: "PA" } },
  };
  if (area) properties.Area = { select: { name: area } };
  if (priority) properties.Priority = { select: { name: priority } };
  if (dueDate) properties["Due Date"] = { date: { start: dueDate } };

  await fetch("https://api.notion.com/v1/pages", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.NOTION_TOKEN}`,
      "Notion-Version": "2022-06-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      parent: { database_id: env.NOTION_TASKS_DB },
      properties,
    }),
  });
}

interface LLMMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_call_id?: string;
}

interface ChatRequest {
  message: string;
  sessionKey?: string;
}

// ---------------------------------------------------------------------------
// Gateway fetch helper
// ---------------------------------------------------------------------------

async function gatewayFetch(
  env: Env,
  path: string,
  opts: RequestInit = {},
): Promise<Response> {
  const url = `${env.GATEWAY_URL}${path}`;
  const headers = new Headers(opts.headers || {});
  headers.set("X-Auth-Token", env.GATEWAY_TOKEN);
  if (!headers.has("Content-Type") && opts.body) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url, { ...opts, headers, signal: AbortSignal.timeout(25000) });
}

// ---------------------------------------------------------------------------
// Rate limiter (in-memory, per-isolate)
// ---------------------------------------------------------------------------

const rateLimitMap = new Map<string, { count: number; resetAt: number }>();

function checkRateLimit(key: string, maxPerMinute: number): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(key);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(key, { count: 1, resetAt: now + 60000 });
    return true;
  }
  entry.count++;
  return entry.count <= maxPerMinute;
}

const PUBLIC_PATHS = new Set(["/", "/health", "/webhook/telegram"]);

// ---------------------------------------------------------------------------
// Gemini -> OpenAI tool format converter
// ---------------------------------------------------------------------------

interface GeminiParam {
  type: string;
  description?: string;
  enum?: string[];
  items?: GeminiParam;
  properties?: Record<string, GeminiParam>;
  required?: string[];
}

interface GeminiTool {
  name: string;
  description: string;
  parameters: {
    type: string;
    properties: Record<string, GeminiParam>;
    required?: string[];
  };
}

function convertGeminiSchema(param: GeminiParam): Record<string, unknown> {
  const out: Record<string, unknown> = { type: param.type };
  if (param.description) out.description = param.description;
  if (param.enum) out.enum = param.enum;
  if (param.items) out.items = convertGeminiSchema(param.items);
  if (param.properties) {
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(param.properties)) {
      props[k] = convertGeminiSchema(v);
    }
    out.properties = props;
    if (param.required) out.required = param.required;
  }
  return out;
}

function convertToolsToOpenAI(
  tools: GeminiTool[],
): Array<{ type: "function"; function: { name: string; description: string; parameters: Record<string, unknown> } }> {
  return tools.map((t) => ({
    type: "function" as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: {
        type: "object",
        properties: Object.fromEntries(
          Object.entries(t.parameters.properties).map(([k, v]) => [k, convertGeminiSchema(v)]),
        ),
        required: t.parameters.required || [],
      },
    },
  }));
}

let _cachedOpenAITools: ReturnType<typeof convertToolsToOpenAI> | null = null;
function getOpenAITools() {
  if (!_cachedOpenAITools) {
    _cachedOpenAITools = convertToolsToOpenAI(PA_TOOLS);
  }
  return _cachedOpenAITools;
}

// ---------------------------------------------------------------------------
// DeepSeek caller with tool loop
// ---------------------------------------------------------------------------

async function callDeepSeek(
  env: Env,
  systemPrompt: string,
  messages: LLMMessage[],
  maxIterations: number = 3,
  maxTokens: number = 2048,
  executeToolFn: (name: string, args: Record<string, unknown>) => Promise<Record<string, unknown>>,
): Promise<{ reply: string; toolUsed: string | null; toolResult: Record<string, unknown> | null; usage?: { input_tokens: number; output_tokens: number; total_tokens: number } }> {
  const callStart = Date.now();
  const allMessages: Array<Record<string, unknown>> = [
    { role: "system", content: systemPrompt },
    ...messages.map((m) => {
      const msg: Record<string, unknown> = { role: m.role, content: m.content };
      if (m.tool_call_id) msg.tool_call_id = m.tool_call_id;
      return msg;
    }),
  ];

  let lastToolName: string | null = null;
  let lastToolResult: Record<string, unknown> | null = null;
  let usageInfo: { input_tokens: number; output_tokens: number; total_tokens: number } | undefined;

  for (let iter = 0; iter < maxIterations; iter++) {
    const resp = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
      },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: allMessages,
        tools: getOpenAITools(),
        tool_choice: "auto",
        max_tokens: maxTokens,
        temperature: 0.7,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`DeepSeek API error ${resp.status}: ${errText.slice(0, 200)}`);
    }

    const data = (await resp.json()) as {
      choices: Array<{
        message: {
          role: string;
          content?: string | null;
          tool_calls?: Array<{
            id: string;
            function: { name: string; arguments: string };
          }>;
        };
        finish_reason: string;
      }>;
      usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
    };

    usageInfo = data.usage ? {
      input_tokens: data.usage.prompt_tokens,
      output_tokens: data.usage.completion_tokens,
      total_tokens: data.usage.total_tokens,
    } : usageInfo;

    const choice = data.choices[0];
    if (!choice) throw new Error("No response from DeepSeek");

    const msg = choice.message;

    // If no tool calls, return the text response
    if (!msg.tool_calls || msg.tool_calls.length === 0) {
      return {
        reply: msg.content || "(no response)",
        toolUsed: lastToolName,
        toolResult: lastToolResult,
        usage: usageInfo,
      };
    }

    // Process tool calls
    allMessages.push({
      role: "assistant",
      content: msg.content || null,
      tool_calls: msg.tool_calls,
    });

    for (const tc of msg.tool_calls) {
      const fnName = tc.function.name;
      let fnArgs: Record<string, unknown> = {};
      try {
        fnArgs = JSON.parse(tc.function.arguments || "{}");
      } catch {
        fnArgs = {};
      }

      let result: Record<string, unknown>;
      try {
        result = await executeToolFn(fnName, fnArgs);
      } catch (err) {
        result = { error: `Tool execution failed: ${(err as Error).message}` };
      }

      lastToolName = fnName;
      lastToolResult = result;

      allMessages.push({
        role: "tool",
        tool_call_id: tc.id,
        content: JSON.stringify(result).slice(0, 8000),
      });
    }
  }

  return {
    reply: "(max tool iterations reached)",
    toolUsed: lastToolName,
    toolResult: lastToolResult,
    usage: usageInfo,
  };
}

// ---------------------------------------------------------------------------
// PA Tool Declarations (~28 personal life tools)
// ---------------------------------------------------------------------------

const PA_TOOLS: GeminiTool[] = [
  // --- Weather ---
  {
    name: "get_weather",
    description: "Get current weather and forecast. Defaults to Flagstaff AZ.",
    parameters: {
      type: "object",
      properties: {
        location: { type: "string", description: "City name (default: Flagstaff)" },
        latitude: { type: "number", description: "Latitude override" },
        longitude: { type: "number", description: "Longitude override" },
      },
      required: [],
    },
  },
  // --- Nutrition ---
  {
    name: "nutrition_lookup",
    description: "Look up nutrition facts for a food item using USDA FoodData Central.",
    parameters: {
      type: "object",
      properties: {
        food: { type: "string", description: "Food item to look up" },
      },
      required: ["food"],
    },
  },
  // --- Memory ---
  {
    name: "search_memory",
    description: "Search long-term memories and reminders by keyword. NOT for Apple Notes — use get_notes/list_notes for those.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query" },
        tag: { type: "string", description: "Optional tag filter" },
        limit: { type: "number", description: "Max results (default 10)" },
      },
      required: ["query"],
    },
  },
  {
    name: "save_memory",
    description: "Save a long-term memory or reminder. NOT for Apple Notes — use save_note for those.",
    parameters: {
      type: "object",
      properties: {
        content: { type: "string", description: "Content to save" },
        tags: { type: "string", description: "Comma-separated tags" },
        remind_at: { type: "string", description: "ISO timestamp for reminder" },
      },
      required: ["content"],
    },
  },
  // --- Gmail ---
  {
    name: "get_gmail_inbox",
    description: "Get recent emails from Gmail inbox.",
    parameters: {
      type: "object",
      properties: {
        max_results: { type: "number", description: "Max emails to return (default 10)" },
        query: { type: "string", description: "Gmail search query (e.g. 'from:boss is:unread')" },
      },
      required: [],
    },
  },
  {
    name: "send_email",
    description: "Send an email via Gmail.",
    parameters: {
      type: "object",
      properties: {
        to: { type: "string", description: "Recipient email" },
        subject: { type: "string", description: "Email subject" },
        body: { type: "string", description: "Email body (plain text)" },
      },
      required: ["to", "subject", "body"],
    },
  },
  {
    name: "trash_emails",
    description: "Move emails to trash by message IDs.",
    parameters: {
      type: "object",
      properties: {
        message_ids: { type: "string", description: "Comma-separated message IDs" },
      },
      required: ["message_ids"],
    },
  },
  {
    name: "label_emails",
    description: "Add/remove labels on emails.",
    parameters: {
      type: "object",
      properties: {
        message_ids: { type: "string", description: "Comma-separated message IDs" },
        add_labels: { type: "string", description: "Labels to add (comma-separated)" },
        remove_labels: { type: "string", description: "Labels to remove (comma-separated)" },
      },
      required: ["message_ids"],
    },
  },
  {
    name: "get_gmail_labels",
    description: "List all Gmail labels.",
    parameters: { type: "object", properties: {}, required: [] },
  },
  // --- Calendar ---
  {
    name: "get_calendar_today",
    description: "Get today's calendar events.",
    parameters: { type: "object", properties: {}, required: [] },
  },
  {
    name: "create_calendar_event",
    description: "Create a new calendar event.",
    parameters: {
      type: "object",
      properties: {
        summary: { type: "string", description: "Event title" },
        start_time: { type: "string", description: "Start time (ISO format or natural language)" },
        end_time: { type: "string", description: "End time (ISO format)" },
        description: { type: "string", description: "Event description" },
        location: { type: "string", description: "Event location" },
        calendar_id: { type: "string", description: "Calendar ID (default: primary)" },
      },
      required: ["summary", "start_time"],
    },
  },
  {
    name: "get_calendar_upcoming",
    description: "Get upcoming calendar events for the next N days.",
    parameters: {
      type: "object",
      properties: {
        days: { type: "number", description: "Number of days to look ahead (default 7)" },
      },
      required: [],
    },
  },
  {
    name: "list_calendars",
    description: "List all available Google Calendars.",
    parameters: { type: "object", properties: {}, required: [] },
  },
  // --- Web ---
  {
    name: "web_search",
    description: "Search the web using DuckDuckGo or Perplexity.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query" },
        num_results: { type: "number", description: "Number of results (default 5)" },
      },
      required: ["query"],
    },
  },
  {
    name: "web_fetch",
    description: "Fetch content from a URL and return text.",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string", description: "URL to fetch" },
        max_length: { type: "number", description: "Max chars to return (default 5000)" },
      },
      required: ["url"],
    },
  },
  // --- Compute ---
  {
    name: "compute_math",
    description: "Evaluate a math expression (e.g. '2+2', 'sqrt(144)', '15% of 200').",
    parameters: {
      type: "object",
      properties: {
        expression: { type: "string", description: "Math expression to evaluate" },
      },
      required: ["expression"],
    },
  },
  {
    name: "compute_convert",
    description: "Convert between units (e.g. '5 miles to km', '100 F to C').",
    parameters: {
      type: "object",
      properties: {
        value: { type: "number", description: "Value to convert" },
        from_unit: { type: "string", description: "Source unit" },
        to_unit: { type: "string", description: "Target unit" },
      },
      required: ["value", "from_unit", "to_unit"],
    },
  },
  // --- SMS ---
  {
    name: "send_sms",
    description: "Send an SMS message via Twilio.",
    parameters: {
      type: "object",
      properties: {
        to: { type: "string", description: "Phone number (E.164 format)" },
        message: { type: "string", description: "Message body" },
      },
      required: ["to", "message"],
    },
  },
  {
    name: "sms_history",
    description: "Get recent SMS message history.",
    parameters: {
      type: "object",
      properties: {
        limit: { type: "number", description: "Number of messages (default 10)" },
        phone: { type: "string", description: "Filter by phone number" },
      },
      required: [],
    },
  },
  // --- Plan / Research ---
  {
    name: "plan_my_day",
    description: "Generate a structured daily plan based on calendar, weather, habits, and reminders.",
    parameters: {
      type: "object",
      properties: {
        focus: { type: "string", description: "What to focus on today (optional)" },
      },
      required: [],
    },
  },
  {
    name: "plan_my_week",
    description: "Generate a weekly plan with calendar events grouped by day.",
    parameters: {
      type: "object",
      properties: {
        focus: { type: "string", description: "Weekly focus area (optional)" },
      },
      required: [],
    },
  },
  {
    name: "perplexity_research",
    description: "Research a topic using Perplexity AI for up-to-date information.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Research question" },
        detail_level: { type: "string", description: "brief or detailed (default: brief)", enum: ["brief", "detailed"] },
      },
      required: ["query"],
    },
  },
  // --- Life OS: Kitchen Inventory ---
  {
    name: "kitchen_inventory",
    description: "Manage kitchen/pantry inventory. Track ingredients, check what you have, plan grocery trips.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform",
          enum: ["list", "add", "remove", "update", "check", "expiring", "grocery_list"],
        },
        items: { type: "string", description: "Comma-separated items for add/remove/check" },
        quantities: { type: "string", description: "Comma-separated quantities matching items" },
        category: { type: "string", description: "Category filter (produce, dairy, meat, pantry, frozen, other)" },
      },
      required: ["action"],
    },
  },
  // --- Life OS: Meal Planner ---
  {
    name: "meal_planner",
    description: "Plan meals, get recipe suggestions based on inventory, generate grocery lists.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform",
          enum: ["suggest", "plan", "grocery", "log"],
        },
        meal_type: { type: "string", description: "breakfast, lunch, dinner, or snack" },
        preferences: { type: "string", description: "Dietary preferences or ingredients to use" },
        days: { type: "number", description: "Number of days to plan (default 3)" },
      },
      required: ["action"],
    },
  },
  // --- Life OS: Wardrobe Tracker ---
  {
    name: "wardrobe_tracker",
    description: "Track wardrobe items, get outfit suggestions based on weather.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform",
          enum: ["list", "add", "remove", "outfit"],
        },
        item: { type: "string", description: "Item description for add/remove" },
        category: { type: "string", description: "Category (tops, bottoms, shoes, outerwear, accessories)" },
        weather: { type: "string", description: "Weather condition for outfit suggestion" },
        occasion: { type: "string", description: "Occasion (casual, work, formal, workout)" },
      },
      required: ["action"],
    },
  },
  // --- Life OS: Habit Tracker ---
  {
    name: "habit_tracker",
    description: "Track daily habits with streaks. Log completions, view status, manage habits.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform",
          enum: ["log", "status", "add", "remove", "history", "weekly"],
        },
        habit: { type: "string", description: "Habit name (e.g. water_8cups, workout)" },
        note: { type: "string", description: "Optional note for log entries" },
      },
      required: ["action"],
    },
  },
  // --- Life OS: Science Day Planner ---
  {
    name: "science_day_planner",
    description: "Plan your day using circadian science — optimal times for focus, exercise, meals, and sleep.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          description: "Action to perform",
          enum: ["plan", "energy", "sleep", "review"],
        },
        wake_time: { type: "string", description: "Wake time (e.g. '7:00 AM', default: 7am)" },
        priorities: { type: "string", description: "Comma-separated priorities for the day" },
      },
      required: ["action"],
    },
  },
  // --- Course Maker ---
  {
    name: "create_course",
    description: "Create a mini-course from a URL, PDF link, or raw text. AI extracts concepts, generates lessons with explanations, and creates quizzes.",
    parameters: {
      type: "object",
      properties: {
        source: { type: "string", description: "The content source — a URL, PDF link, or raw text to learn from" },
        source_type: { type: "string", description: "Type of source: 'url', 'pdf_url', or 'text' (auto-detected if not provided)", enum: ["url", "text", "pdf_url"] },
        title: { type: "string", description: "Optional course title (auto-generated if not provided)" },
      },
      required: ["source"],
    },
  },
  {
    name: "list_courses",
    description: "List all courses the user has created.",
    parameters: {
      type: "object",
      properties: {},
      required: [],
    },
  },
  {
    name: "get_lesson",
    description: "Get a specific lesson by ID, or get the next incomplete lesson in a course.",
    parameters: {
      type: "object",
      properties: {
        lesson_id: { type: "string", description: "Specific lesson ID to fetch" },
        course_id: { type: "string", description: "Course ID to get the next incomplete lesson from" },
      },
      required: [],
    },
  },
  {
    name: "take_quiz",
    description: "Submit quiz answers for a lesson. Answers are numbered (1-based) corresponding to quiz questions.",
    parameters: {
      type: "object",
      properties: {
        course_id: { type: "string", description: "Course ID" },
        lesson_id: { type: "string", description: "Lesson ID" },
        answers: { type: "string", description: "Comma-separated answer indices (e.g. '2,1,3,4' for questions 1-4)" },
      },
      required: ["course_id", "lesson_id", "answers"],
    },
  },
  {
    name: "course_progress",
    description: "Get progress summary for a course — completion %, scores, and what's next.",
    parameters: {
      type: "object",
      properties: {
        course_id: { type: "string", description: "Course ID to check progress for" },
      },
      required: ["course_id"],
    },
  },
  // --- Flashcards (Spaced Repetition) ---
  {
    name: "study_flashcards",
    description: "Get flashcards due for review from a course. Uses spaced repetition (SM-2 algorithm) to optimize learning.",
    parameters: {
      type: "object",
      properties: {
        course_id: { type: "string", description: "Course ID to study flashcards from" },
        limit: { type: "number", description: "Max cards to review (default 10)" },
      },
      required: ["course_id"],
    },
  },
  {
    name: "review_flashcard",
    description: "Rate how well you remembered a flashcard (0=forgot, 3=hard, 5=easy). Adjusts the review schedule.",
    parameters: {
      type: "object",
      properties: {
        flashcard_id: { type: "string", description: "Flashcard ID" },
        quality: { type: "number", description: "Rating 0-5 (0=forgot, 1=bad, 2=poor, 3=hard, 4=good, 5=easy)" },
      },
      required: ["flashcard_id", "quality"],
    },
  },
  // --- Podcast / Audio ---
  {
    name: "create_podcast",
    description: "Turn a URL, article, or text into a podcast-style audio summary. Can send as voice message.",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string", description: "URL to turn into a podcast" },
        text: { type: "string", description: "Raw text to turn into a podcast (if no URL)" },
        title: { type: "string", description: "Title for the podcast episode" },
        style: { type: "string", description: "Style: summary (~500 words), deep_dive (~1000), quick_brief (~200)", enum: ["summary", "deep_dive", "quick_brief"] },
      },
      required: [],
    },
  },
  // --- Knowledge Graph ---
  {
    name: "knowledge_graph",
    description: "View your knowledge graph — entities (people, places, projects, goals) and their connections extracted from your memories.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string", description: "Action: 'view' (graph), 'stats' (summary), 'search' (find related)", enum: ["view", "stats", "search"] },
        entity_name: { type: "string", description: "Entity name to focus on (for view/search)" },
        query: { type: "string", description: "Query to find related entities and memories (for search)" },
      },
      required: ["action"],
    },
  },
  {
    name: "get_current_conditions",
    description: "Get current time, date, weather, and whether Miles is in work hours. Useful for scheduling and context-aware responses.",
    parameters: {
      type: "object",
      properties: {},
      required: [],
    },
  },
  // --- Notes (synced from Apple Notes via n8n) ---
  {
    name: "save_note",
    description: "Save a note to persistent storage. Used for saving information, ideas, reminders, or synced Apple Notes.",
    parameters: {
      type: "object",
      properties: {
        title: { type: "string", description: "Note title" },
        content: { type: "string", description: "Note content (plain text or markdown)" },
        folder: { type: "string", description: "Folder/category (e.g. 'ideas', 'work', 'personal')" },
        source: { type: "string", description: "Where the note came from (e.g. 'apple_notes', 'telegram', 'pa')" },
      },
      required: ["title", "content"],
    },
  },
  {
    name: "get_notes",
    description: "Retrieve saved notes. Filter by folder or search by keyword.",
    parameters: {
      type: "object",
      properties: {
        folder: { type: "string", description: "Filter by folder name" },
        search: { type: "string", description: "Search keyword in title/content" },
        limit: { type: "number", description: "Max notes to return (default 10)" },
      },
      required: [],
    },
  },
  {
    name: "list_notes",
    description: "List all note titles and folders. Quick overview without full content.",
    parameters: {
      type: "object",
      properties: {
        folder: { type: "string", description: "Filter by folder name" },
      },
      required: [],
    },
  },
  // --- Outlook Calendar ---
  {
    name: "get_outlook_calendar",
    description: "Get Miles's upcoming events from NAU Outlook calendar and PDC Student Worker calendar. Shows classes, meetings, work shifts.",
    parameters: {
      type: "object",
      properties: {
        days_ahead: { type: "number", description: "How many days ahead to look (default: 14, max: 30)" },
      },
      required: [],
    },
  },
];

// ---------------------------------------------------------------------------
// Tool executor — dispatches to gateway, direct APIs, or KV
// ---------------------------------------------------------------------------

async function executeTool(
  env: Env,
  name: string,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  switch (name) {
    // ── Gateway-proxied tools ──────────────────────────────────────────

    case "search_memory": {
      const resp = await gatewayFetch(env, `/api/memories?query=${encodeURIComponent(String(args.query || ""))}&tag=${encodeURIComponent(String(args.tag || ""))}&limit=${args.limit || 10}`);
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "save_memory": {
      const resp = await gatewayFetch(env, "/api/memories", {
        method: "POST",
        body: JSON.stringify({
          content: args.content,
          tags: args.tags ? String(args.tags).split(",").map((t: string) => t.trim()) : [],
          remind_at: args.remind_at || undefined,
        }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "get_gmail_inbox": {
      const qs = new URLSearchParams();
      if (args.max_results) qs.set("maxResults", String(args.max_results));
      if (args.query) qs.set("q", String(args.query));
      const resp = await gatewayFetch(env, `/api/gmail/inbox?${qs}`);
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "send_email": {
      const resp = await gatewayFetch(env, "/api/gmail/send", {
        method: "POST",
        body: JSON.stringify({ to: args.to, subject: args.subject, body: args.body }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "trash_emails": {
      const resp = await gatewayFetch(env, "/api/gmail/trash", {
        method: "POST",
        body: JSON.stringify({ message_ids: String(args.message_ids).split(",").map((s: string) => s.trim()) }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "label_emails": {
      const resp = await gatewayFetch(env, "/api/gmail/labels/modify", {
        method: "POST",
        body: JSON.stringify({
          message_ids: String(args.message_ids).split(",").map((s: string) => s.trim()),
          add_labels: args.add_labels ? String(args.add_labels).split(",").map((s: string) => s.trim()) : [],
          remove_labels: args.remove_labels ? String(args.remove_labels).split(",").map((s: string) => s.trim()) : [],
        }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "get_gmail_labels": {
      const resp = await gatewayFetch(env, "/api/gmail/labels");
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "get_calendar_today": {
      const resp = await gatewayFetch(env, "/api/calendar/today");
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "create_calendar_event": {
      const resp = await gatewayFetch(env, "/api/calendar/create", {
        method: "POST",
        body: JSON.stringify(args),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "get_calendar_upcoming": {
      const days = args.days || 7;
      const resp = await gatewayFetch(env, `/api/calendar/upcoming?days=${days}`);
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "list_calendars": {
      const resp = await gatewayFetch(env, "/api/calendar/list");
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "web_search": {
      const resp = await gatewayFetch(env, "/api/mcp/web_search", {
        method: "POST",
        body: JSON.stringify({ query: args.query, num_results: args.num_results || 5 }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "web_fetch": {
      const resp = await gatewayFetch(env, "/api/mcp/web_fetch", {
        method: "POST",
        body: JSON.stringify({ url: args.url, max_length: args.max_length || 5000 }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "compute_math": {
      const resp = await gatewayFetch(env, "/api/mcp/compute_math", {
        method: "POST",
        body: JSON.stringify({ expression: args.expression }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "compute_convert": {
      const resp = await gatewayFetch(env, "/api/mcp/compute_convert", {
        method: "POST",
        body: JSON.stringify({ value: args.value, from_unit: args.from_unit, to_unit: args.to_unit }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "send_sms": {
      const resp = await gatewayFetch(env, "/api/mcp/send_sms", {
        method: "POST",
        body: JSON.stringify({ to: args.to, message: args.message }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "sms_history": {
      const qs = new URLSearchParams();
      if (args.limit) qs.set("limit", String(args.limit));
      if (args.phone) qs.set("phone", String(args.phone));
      const resp = await gatewayFetch(env, `/api/mcp/sms_history?${qs}`);
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    case "perplexity_research": {
      // Smart redirect: if query is about weather, crypto, or nutrition, use those tools
      const q = String(args.query || "").toLowerCase();
      if (/weather|temperature|forecast|rain/.test(q)) {
        return executeTool(env, "get_weather", {});
      }
      if (/calories|nutrition|protein|carbs|fat/.test(q) && q.split(" ").length <= 4) {
        const food = q.replace(/calories|nutrition|protein|carbs|fat|in|of|how|many|much/gi, "").trim();
        if (food) return executeTool(env, "nutrition_lookup", { food });
      }

      const resp = await gatewayFetch(env, "/api/perplexity-research", {
        method: "POST",
        body: JSON.stringify({ query: args.query, detail_level: args.detail_level || "brief" }),
      });
      return resp.ok ? (await resp.json()) as Record<string, unknown> : { error: `Gateway error: ${resp.status}` };
    }

    // ── Plan tools (gateway-backed with parallel fetches) ─────────────

    case "plan_my_day": {
      const [calRes, wxRes, habitsRaw, remindersRes] = await Promise.all([
        gatewayFetch(env, "/api/calendar/today").then(r => r.json()).catch(() => ({ events: [] })),
        fetch("https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&forecast_days=1&timezone=America%2FPhoenix")
          .then(r => r.json()).catch(() => ({})),
        env.KV_CACHE.get("lifeos:habits"),
        gatewayFetch(env, "/api/memories?tag=reminder&limit=10").then(r => r.json()).catch(() => ({ memories: [] })),
      ]);
      return {
        calendar: calRes,
        weather: wxRes,
        habits: habitsRaw ? JSON.parse(habitsRaw as string) : {},
        reminders: remindersRes,
        focus: args.focus || "all",
        date: new Date().toLocaleDateString("en-CA", { timeZone: "America/Phoenix" }),
        schedule: "Work 5pm-10pm MST (Tue-Sun). Monday OFF. Soccer Thursday ~9:20pm.",
      };
    }

    case "plan_my_week": {
      const calWeek = await gatewayFetch(env, "/api/calendar/upcoming?days=7")
        .then(r => r.json())
        .catch(() => ({ events: [] }));
      return {
        calendar: calWeek,
        focus: args.focus || "all",
        schedule: "Work 5pm-10pm MST (Tue-Sun). Monday OFF. Soccer Thursday ~9:20pm.",
      };
    }

    // ── Direct API tools (no gateway needed) ──────────────────────────

    case "get_weather": {
      const lat = args.latitude || 35.1983;
      const lon = args.longitude || -111.6513;
      const locName = args.location || "Flagstaff, AZ";

      const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=3&timezone=America%2FPhoenix`;

      try {
        const resp = await fetch(url);
        if (!resp.ok) return { error: `Weather API error: ${resp.status}` };
        const wx = (await resp.json()) as Record<string, unknown>;

        const wxCodes: Record<number, string> = {
          0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
          45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
          55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
          71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
          80: "Rain showers", 81: "Heavy rain showers", 82: "Violent rain",
          85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
        };

        const current = wx.current as Record<string, unknown> | undefined;
        const daily = wx.daily as Record<string, unknown[]> | undefined;

        return {
          location: locName,
          current: {
            temperature: current?.temperature_2m,
            feels_like: current?.apparent_temperature,
            humidity: current?.relative_humidity_2m,
            wind_mph: current?.wind_speed_10m,
            condition: wxCodes[(current?.weather_code as number) || 0] || "Unknown",
          },
          forecast: daily?.temperature_2m_max?.map((hi, i) => ({
            day: i === 0 ? "Today" : i === 1 ? "Tomorrow" : `Day ${i + 1}`,
            high: hi,
            low: (daily.temperature_2m_min as number[])?.[i],
            rain_pct: (daily.precipitation_probability_max as number[])?.[i] || 0,
            condition: wxCodes[(daily.weather_code as number[])?.[i] || 0] || "Unknown",
          })),
        };
      } catch (e) {
        return { error: `Weather fetch failed: ${(e as Error).message}` };
      }
    }

    case "nutrition_lookup": {
      const food = String(args.food || "");
      if (!food) return { error: "food parameter required" };
      try {
        const resp = await fetch(`https://api.nal.usda.gov/fdc/v1/foods/search?query=${encodeURIComponent(food)}&pageSize=3&api_key=DEMO_KEY`);
        if (!resp.ok) return { error: `USDA API error: ${resp.status}` };
        const data = (await resp.json()) as { foods?: Array<Record<string, unknown>> };
        return {
          query: food,
          results: (data.foods || []).slice(0, 3).map((f) => ({
            name: f.description,
            brand: f.brandName || f.brandOwner || null,
            nutrients: ((f.foodNutrients as Array<Record<string, unknown>>) || [])
              .filter((n) => {
                const name = String(n.nutrientName || "").toLowerCase();
                return ["energy", "protein", "total lipid", "carbohydrate", "fiber", "sugars", "sodium", "cholesterol"].some((k) => name.includes(k));
              })
              .map((n) => ({
                name: n.nutrientName,
                value: n.value,
                unit: n.unitName,
              })),
          })),
        };
      } catch (e) {
        return { error: `Nutrition fetch failed: ${(e as Error).message}` };
      }
    }

    // ── Life OS: KV-backed tools ──────────────────────────────────────

    case "kitchen_inventory": {
      const KV = env.KV_CACHE;
      const action = String(args.action || "list");
      const raw = await KV.get("lifeos:kitchen_inventory");
      let inventory: Record<string, { quantity: string; category: string; added: string }> = raw ? JSON.parse(raw) : {};

      if (action === "list") {
        const cat = args.category ? String(args.category).toLowerCase() : null;
        const items = Object.entries(inventory)
          .filter(([, v]) => !cat || v.category === cat)
          .map(([name, v]) => ({ name, ...v }));
        return { items, total: items.length };
      }

      if (action === "add") {
        const itemList = String(args.items || "").split(",").map(s => s.trim()).filter(Boolean);
        const qtyList = String(args.quantities || "").split(",").map(s => s.trim());
        const cat = String(args.category || "other").toLowerCase();
        const added: string[] = [];
        for (let i = 0; i < itemList.length; i++) {
          const key = itemList[i].toLowerCase();
          inventory[key] = { quantity: qtyList[i] || "1", category: cat, added: new Date().toISOString().split("T")[0] };
          added.push(key);
        }
        await KV.put("lifeos:kitchen_inventory", JSON.stringify(inventory));
        return { added, total: Object.keys(inventory).length };
      }

      if (action === "remove") {
        const itemList = String(args.items || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
        const removed: string[] = [];
        for (const item of itemList) {
          if (inventory[item]) { delete inventory[item]; removed.push(item); }
        }
        await KV.put("lifeos:kitchen_inventory", JSON.stringify(inventory));
        return { removed, total: Object.keys(inventory).length };
      }

      if (action === "check") {
        const itemList = String(args.items || "").split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
        const result = itemList.map(item => ({
          item,
          in_stock: !!inventory[item],
          quantity: inventory[item]?.quantity || null,
        }));
        return { items: result };
      }

      if (action === "expiring") {
        const week = 7 * 86400000;
        const soon = Object.entries(inventory)
          .filter(([, v]) => {
            const addedDate = new Date(v.added).getTime();
            const perishable = ["produce", "dairy", "meat"].includes(v.category);
            return perishable && (Date.now() - addedDate > week);
          })
          .map(([name, v]) => ({ name, ...v, days_old: Math.floor((Date.now() - new Date(v.added).getTime()) / 86400000) }));
        return { expiring_soon: soon, count: soon.length };
      }

      if (action === "grocery_list") {
        const essentials = ["eggs", "milk", "bread", "butter", "rice", "chicken", "onions", "garlic", "tomatoes", "salt"];
        const missing = essentials.filter(e => !inventory[e]);
        return { needed: missing, have: essentials.filter(e => inventory[e]) };
      }

      return { error: `Unknown kitchen action: ${action}` };
    }

    case "meal_planner": {
      const KV = env.KV_CACHE;
      const action = String(args.action || "suggest");

      if (action === "suggest") {
        const invRaw = await KV.get("lifeos:kitchen_inventory");
        const inv = invRaw ? Object.keys(JSON.parse(invRaw)) : [];
        return {
          available_ingredients: inv.slice(0, 20),
          meal_type: args.meal_type || "any",
          preferences: args.preferences || "none",
          instruction: "Based on available ingredients, suggest 3 meals. Be creative with what's available.",
        };
      }

      if (action === "plan") {
        const days = Number(args.days || 3);
        const planRaw = await KV.get("lifeos:meal_plan");
        return {
          current_plan: planRaw ? JSON.parse(planRaw) : null,
          days_requested: days,
          preferences: args.preferences || "balanced, healthy",
        };
      }

      if (action === "log") {
        const today = new Date().toISOString().split("T")[0];
        const logKey = `lifeos:meal_log:${today}`;
        const logRaw = await KV.get(logKey);
        const log: Array<{ meal: string; type: string; time: string }> = logRaw ? JSON.parse(logRaw) : [];
        log.push({
          meal: String(args.preferences || "meal"),
          type: String(args.meal_type || "other"),
          time: new Date().toISOString(),
        });
        await KV.put(logKey, JSON.stringify(log), { expirationTtl: 30 * 86400 });
        return { logged: true, today_meals: log.length };
      }

      if (action === "grocery") {
        const invRaw = await KV.get("lifeos:kitchen_inventory");
        const inv = invRaw ? Object.keys(JSON.parse(invRaw)) : [];
        return {
          current_inventory: inv,
          instruction: "Generate a grocery list for the week based on healthy meal planning. Exclude items already in inventory.",
        };
      }

      return { error: `Unknown meal_planner action: ${action}` };
    }

    case "wardrobe_tracker": {
      const KV = env.KV_CACHE;
      const action = String(args.action || "list");
      const raw = await KV.get("lifeos:wardrobe");
      let wardrobe: Record<string, Array<{ item: string; added: string }>> = raw ? JSON.parse(raw) : {
        tops: [], bottoms: [], shoes: [], outerwear: [], accessories: [],
      };

      if (action === "list") {
        const cat = args.category ? String(args.category).toLowerCase() : null;
        if (cat && wardrobe[cat]) return { category: cat, items: wardrobe[cat], count: wardrobe[cat].length };
        const total = Object.values(wardrobe).reduce((s, arr) => s + arr.length, 0);
        return { wardrobe, total };
      }

      if (action === "add") {
        const cat = String(args.category || "other").toLowerCase();
        if (!wardrobe[cat]) wardrobe[cat] = [];
        wardrobe[cat].push({ item: String(args.item || "item"), added: new Date().toISOString().split("T")[0] });
        await KV.put("lifeos:wardrobe", JSON.stringify(wardrobe));
        return { added: args.item, category: cat };
      }

      if (action === "remove") {
        const cat = String(args.category || "").toLowerCase();
        const itemStr = String(args.item || "").toLowerCase();
        let removed = false;
        for (const c of (cat ? [cat] : Object.keys(wardrobe))) {
          if (!wardrobe[c]) continue;
          const idx = wardrobe[c].findIndex(i => i.item.toLowerCase().includes(itemStr));
          if (idx >= 0) { wardrobe[c].splice(idx, 1); removed = true; break; }
        }
        if (removed) await KV.put("lifeos:wardrobe", JSON.stringify(wardrobe));
        return { removed, item: args.item };
      }

      if (action === "outfit") {
        return {
          wardrobe,
          weather: args.weather || "unknown",
          occasion: args.occasion || "casual",
          instruction: "Suggest an outfit from the wardrobe items, considering weather and occasion.",
        };
      }

      return { error: `Unknown wardrobe action: ${action}` };
    }

    case "habit_tracker": {
      const KV = env.KV_CACHE;
      const action = String(args.action || "status");
      const today = new Date().toISOString().split("T")[0];

      // Load habits config
      const habitsRaw = await KV.get("lifeos:habits");
      let habits: Record<string, { description?: string }> = habitsRaw
        ? JSON.parse(habitsRaw)
        : { water_8cups: { description: "Drink 8 cups of water" }, sleep_8hrs: { description: "Get 8 hours of sleep" }, workout: { description: "Exercise" }, stretch: { description: "Stretch/mobility" }, healthy_meal: { description: "Eat a healthy meal" } };

      if (action === "status") {
        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const log: Record<string, { done: boolean; time: string; note?: string }> = logRaw ? JSON.parse(logRaw) : {};
        const habitStatus = Object.entries(habits).map(([name, cfg]) => ({
          habit: name,
          description: cfg.description || name,
          done: log[name]?.done || false,
          time: log[name]?.time || null,
          note: log[name]?.note || null,
        }));
        const done = habitStatus.filter(h => h.done).length;
        return { date: today, habits: habitStatus, completed: done, total: habitStatus.length, pct: Math.round((done / habitStatus.length) * 100) };
      }

      if (action === "log") {
        const habit = String(args.habit || "").toLowerCase().replace(/\s+/g, "_");
        if (!habit) return { error: "habit parameter required" };
        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const log: Record<string, { done: boolean; time: string; note?: string }> = logRaw ? JSON.parse(logRaw) : {};
        log[habit] = { done: true, time: new Date().toISOString(), note: args.note ? String(args.note) : undefined };
        await KV.put(`lifeos:habit_log:${today}`, JSON.stringify(log), { expirationTtl: 90 * 86400 });

        // Calculate streak
        let streak = 1;
        for (let d = 1; d <= 365; d++) {
          const checkDate = new Date(Date.now() - d * 86400000).toISOString().split("T")[0];
          const checkRaw = await KV.get(`lifeos:habit_log:${checkDate}`);
          if (checkRaw) {
            const checkLog = JSON.parse(checkRaw);
            if (checkLog[habit]?.done) streak++;
            else break;
          } else break;
        }

        return { logged: true, habit, streak, date: today };
      }

      if (action === "add") {
        const habit = String(args.habit || "").toLowerCase().replace(/\s+/g, "_");
        if (!habit) return { error: "habit parameter required" };
        habits[habit] = { description: args.note ? String(args.note) : habit };
        await KV.put("lifeos:habits", JSON.stringify(habits));
        return { added: habit, total: Object.keys(habits).length };
      }

      if (action === "remove") {
        const habit = String(args.habit || "").toLowerCase().replace(/\s+/g, "_");
        if (!habit) return { error: "habit parameter required" };
        delete habits[habit];
        await KV.put("lifeos:habits", JSON.stringify(habits));
        return { removed: habit, total: Object.keys(habits).length };
      }

      if (action === "history") {
        const days = 7;
        const history: Array<{ date: string; completed: number; total: number }> = [];
        const habitNames = Object.keys(habits);
        for (let d = 0; d < days; d++) {
          const date = new Date(Date.now() - d * 86400000).toISOString().split("T")[0];
          const logRaw = await KV.get(`lifeos:habit_log:${date}`);
          const log = logRaw ? JSON.parse(logRaw) : {};
          const done = habitNames.filter(h => log[h]?.done).length;
          history.push({ date, completed: done, total: habitNames.length });
        }
        return { history };
      }

      if (action === "weekly") {
        const habitNames = Object.keys(habits);
        const weekly: Record<string, { completed: number; total: number }> = {};
        for (let d = 0; d < 7; d++) {
          const date = new Date(Date.now() - d * 86400000).toISOString().split("T")[0];
          const logRaw = await KV.get(`lifeos:habit_log:${date}`);
          const log = logRaw ? JSON.parse(logRaw) : {};
          weekly[date] = { completed: habitNames.filter(h => log[h]?.done).length, total: habitNames.length };
        }
        return { weekly, average_pct: Math.round(Object.values(weekly).reduce((s, v) => s + (v.completed / v.total) * 100, 0) / 7) };
      }

      return { error: `Unknown habit action: ${action}` };
    }

    case "science_day_planner": {
      const action = String(args.action || "plan");
      const wakeTime = String(args.wake_time || "7:00 AM");

      // Parse wake hour
      const match = wakeTime.match(/(\d+):?(\d*)\s*(am|pm)?/i);
      let wakeHour = 7;
      if (match) {
        wakeHour = parseInt(match[1]);
        if (match[3]?.toLowerCase() === "pm" && wakeHour < 12) wakeHour += 12;
        if (match[3]?.toLowerCase() === "am" && wakeHour === 12) wakeHour = 0;
      }

      if (action === "plan") {
        return {
          wake_time: wakeTime,
          priorities: args.priorities || "work, exercise, learning",
          schedule: {
            morning_peak: { start: `${wakeHour + 1}:00`, end: `${wakeHour + 4}:00`, activity: "Deep focus work (cortisol + dopamine peak)" },
            mid_morning: { start: `${wakeHour + 4}:00`, end: `${wakeHour + 5}:00`, activity: "Exercise (body temp rising, optimal for physical performance)" },
            lunch: { start: `${wakeHour + 5}:00`, end: `${wakeHour + 6}:00`, activity: "Lunch + short walk (aids digestion, resets focus)" },
            afternoon: { start: `${wakeHour + 6}:00`, end: `${wakeHour + 9}:00`, activity: "Creative work / meetings (social cognition peaks)" },
            evening_wind: { start: `${wakeHour + 12}:00`, end: `${wakeHour + 14}:00`, activity: "Light tasks, planning tomorrow, dim lights" },
            sleep_prep: { start: `${wakeHour + 15}:00`, end: `${wakeHour + 16}:00`, activity: "No screens, cool room (68F), melatonin onset" },
          },
          tips: [
            "Get 10 min of morning sunlight within 30 min of waking",
            "Delay caffeine 90 min after waking (let adenosine clear)",
            "Cold exposure (cold shower) for dopamine boost",
            "Eat protein-rich breakfast to stabilize blood sugar",
          ],
        };
      }

      if (action === "energy") {
        const hour = new Date().getHours();
        const hoursAwake = (hour - wakeHour + 24) % 24;
        let energyLevel: string;
        let suggestion: string;
        if (hoursAwake < 1) { energyLevel = "rising"; suggestion = "Get sunlight, hydrate, light movement. Delay caffeine 90min."; }
        else if (hoursAwake < 4) { energyLevel = "peak"; suggestion = "Do your hardest cognitive work NOW. This is your golden window."; }
        else if (hoursAwake < 6) { energyLevel = "high"; suggestion = "Good for exercise, creative work, or complex problems."; }
        else if (hoursAwake < 8) { energyLevel = "moderate"; suggestion = "Post-lunch dip coming. Short walk or power nap (20min max)."; }
        else if (hoursAwake < 12) { energyLevel = "moderate"; suggestion = "Good for social tasks, meetings, lighter creative work."; }
        else if (hoursAwake < 14) { energyLevel = "declining"; suggestion = "Wind down. Plan tomorrow. Dim lights."; }
        else { energyLevel = "low"; suggestion = "Stop screens. Cool room to 68F. Read or meditate."; }

        return { energy_level: energyLevel, hours_awake: hoursAwake, suggestion, current_hour: hour };
      }

      if (action === "sleep") {
        return {
          optimal_bedtime: `${(wakeHour - 8 + 24) % 24}:00`,
          wake_time: wakeTime,
          sleep_duration: "7-9 hours recommended",
          tips: [
            "Stop caffeine 10 hours before bed",
            "Dim lights 2 hours before bed",
            "Cool bedroom to 65-68F",
            "No screens 1 hour before bed",
            "Consistent wake time (even weekends) is #1 sleep hack",
          ],
        };
      }

      if (action === "review") {
        const habitsRaw = await env.KV_CACHE.get("lifeos:habits");
        const habits = habitsRaw ? Object.keys(JSON.parse(habitsRaw)) : [];
        const today = new Date().toISOString().split("T")[0];
        const logRaw = await env.KV_CACHE.get(`lifeos:habit_log:${today}`);
        const log = logRaw ? JSON.parse(logRaw) : {};
        return {
          date: today,
          habits_completed: habits.filter(h => log[h]?.done).length,
          habits_total: habits.length,
          instruction: "Review the day: what went well, what could improve, plan for tomorrow.",
        };
      }

      return { error: `Unknown science_day_planner action: ${action}` };
    }

    // ── Course Maker tools (D1-backed) ───────────────────────────────

    case "create_course": {
      const source = String(args.source || "");
      let sourceType = String(args.source_type || "");
      if (!sourceType) {
        if (/^https?:\/\/.+\.pdf/i.test(source)) sourceType = "pdf_url";
        else if (/^https?:\/\//.test(source)) sourceType = "url";
        else sourceType = "text";
      }
      await initializeCourseTables(env.DB);
      const course = await createCourse(
        env.DB,
        env.DEEPSEEK_API_KEY,
        env.TELEGRAM_OWNER_ID,
        sourceType as "text" | "url" | "pdf_url",
        source,
        args.title ? String(args.title) : undefined,
      );
      return {
        course_id: course.id,
        title: course.title,
        description: course.description,
        total_lessons: course.total_lessons,
        total_quizzes: course.total_quizzes,
        message: `Course "${course.title}" created with ${course.total_lessons} lessons and ${course.total_quizzes} quizzes. Say "start lesson" to begin!`,
      };
    }

    case "list_courses": {
      await initializeCourseTables(env.DB);
      const courses = await listCourses(env.DB, env.TELEGRAM_OWNER_ID);
      return {
        courses: courses.map(c => ({
          id: c.id,
          title: c.title,
          lessons: c.total_lessons,
          quizzes: c.total_quizzes,
          created: c.created_at,
        })),
        count: courses.length,
      };
    }

    case "get_lesson": {
      await initializeCourseTables(env.DB);
      if (args.lesson_id) {
        const lesson = await getLesson(env.DB, String(args.lesson_id));
        return lesson ? { lesson } : { error: "Lesson not found" };
      }
      if (args.course_id) {
        const next = await getNextLesson(env.DB, env.TELEGRAM_OWNER_ID, String(args.course_id));
        return next ? { lesson: next } : { message: "All lessons completed! Check your progress." };
      }
      return { error: "Provide lesson_id or course_id" };
    }

    case "take_quiz": {
      await initializeCourseTables(env.DB);
      const answerList = String(args.answers).split(",").map(a => parseInt(a.trim()));
      const result = await submitQuiz(
        env.DB,
        env.TELEGRAM_OWNER_ID,
        String(args.course_id),
        String(args.lesson_id),
        answerList,
      );
      return result;
    }

    case "course_progress": {
      await initializeCourseTables(env.DB);
      const progress = await getCourseProgress(env.DB, env.TELEGRAM_OWNER_ID, String(args.course_id));
      return progress;
    }

    // ── Flashcard tools (spaced repetition) ────────────────────────────

    case "study_flashcards": {
      await initializeCourseTables(env.DB);
      const cards = await getFlashcardsForReview(
        env.DB,
        env.TELEGRAM_OWNER_ID,
        String(args.course_id),
        Number(args.limit) || 10,
      );
      if (cards.length === 0) {
        const stats = await getFlashcardStats(env.DB, String(args.course_id));
        return { message: "No flashcards due for review right now!", stats };
      }
      return { cards, count: cards.length };
    }

    case "review_flashcard": {
      await initializeCourseTables(env.DB);
      const result = await reviewFlashcard(
        env.DB,
        String(args.flashcard_id),
        Number(args.quality),
      );
      return result;
    }

    // ── Podcast tools ──────────────────────────────────────────────────

    case "create_podcast": {
      const req: PodcastRequest = {
        url: args.url ? String(args.url) : undefined,
        text: args.text ? String(args.text) : undefined,
        title: args.title ? String(args.title) : undefined,
        style: (args.style as "summary" | "deep_dive" | "quick_brief") || "summary",
      };
      if (!req.url && !req.text) return { error: "Provide a url or text to create a podcast from" };
      const result = await createPodcast(req, env.DEEPSEEK_API_KEY, env.GEMINI_API_KEY);
      // Send audio to Telegram if available
      if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_OWNER_ID) {
        await sendTelegramAudioResult(env.TELEGRAM_BOT_TOKEN, env.TELEGRAM_OWNER_ID, result);
      }
      return {
        title: result.title,
        word_count: result.word_count,
        duration_estimate: result.duration_estimate,
        has_audio: !!result.audio_base64,
        script: result.script.slice(0, 2000),
      };
    }

    // ── Knowledge Graph tools ───────────────────────────────────────────

    case "knowledge_graph": {
      await initializeGraphTables(env.DB);
      const action = String(args.action || "stats");

      if (action === "stats") {
        return await getGraphStats(env.DB, env.TELEGRAM_OWNER_ID);
      }

      if (action === "view") {
        const graph = await getEntityGraph(
          env.DB,
          env.TELEGRAM_OWNER_ID,
          args.entity_name ? String(args.entity_name) : undefined,
        );
        return {
          entities: graph.entities.slice(0, 50),
          relations: graph.relations.slice(0, 100),
          entity_count: graph.entities.length,
          relation_count: graph.relations.length,
        };
      }

      if (action === "search") {
        const query = String(args.query || args.entity_name || "");
        if (!query) return { error: "Provide a query or entity_name to search" };
        const memoryIds = await getRelatedMemories(env.DB, env.TELEGRAM_OWNER_ID, query);
        // Fetch actual memory texts
        if (memoryIds.length === 0) return { message: "No related memories found", query };
        const placeholders = memoryIds.map(() => "?").join(",");
        const mems = await env.DB
          .prepare(`SELECT id, data, category, created_at FROM memories WHERE id IN (${placeholders})`)
          .bind(...memoryIds)
          .all<{ id: string; data: string; category: string; created_at: string }>();
        return {
          query,
          related_memories: mems.results || [],
          count: mems.results?.length || 0,
        };
      }

      return { error: "Unknown action. Use: view, stats, or search" };
    }

    case "get_current_conditions": {
      const now = new Date();
      const mstOffset = -7;
      const mstTime = new Date(now.getTime() + mstOffset * 3600000);
      const hour = mstTime.getUTCHours();
      const dayOfWeek = mstTime.getUTCDay(); // 0=Sun, 1=Mon
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

      const isMonday = dayOfWeek === 1;
      const isWorkHours = !isMonday && hour >= 17 && hour < 22;
      const isSoccerDay = dayOfWeek === 4; // Thursday

      // Fetch weather
      let weather: Record<string, unknown> = {};
      try {
        const wxResp = await fetch("https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&current=temperature_2m,weather_code&temperature_unit=fahrenheit&timezone=America%2FPhoenix");
        if (wxResp.ok) {
          const wx = (await wxResp.json()) as { current?: { temperature_2m?: number; weather_code?: number } };
          const wxCodes: Record<number, string> = { 0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast", 45: "Foggy", 61: "Light Rain", 63: "Rain", 71: "Light Snow", 73: "Snow", 95: "Thunderstorm" };
          weather = {
            temperature_f: wx.current?.temperature_2m,
            condition: wxCodes[wx.current?.weather_code || 0] || "Unknown",
          };
        }
      } catch { /* non-critical */ }

      return {
        time: mstTime.toISOString().replace("T", " ").slice(0, 19) + " MST",
        date: mstTime.toISOString().split("T")[0],
        day: dayNames[dayOfWeek],
        hour_mst: hour,
        is_work_hours: isWorkHours,
        is_monday_off: isMonday,
        is_soccer_day: isSoccerDay,
        work_schedule: isMonday ? "Day OFF" : isWorkHours ? "Currently in work hours (5pm-10pm)" : hour < 17 ? `Work starts in ${17 - hour} hours` : "After work hours",
        weather,
      };
    }

    // ── Notes (KV-backed) ─────────────────────────────────────────────
    case "save_note": {
      const id = `note_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const note = {
        id,
        title: String(args.title || "Untitled"),
        content: String(args.content || ""),
        folder: String(args.folder || "general"),
        source: String(args.source || "pa"),
        created_at: new Date().toISOString(),
      };
      await env.KV.put(`pa:notes:${id}`, JSON.stringify(note));
      // Update index
      const indexRaw = await env.KV.get("pa:notes:index");
      const index: Array<{ id: string; title: string; folder: string; created_at: string }> = indexRaw ? JSON.parse(indexRaw) : [];
      index.unshift({ id, title: note.title, folder: note.folder, created_at: note.created_at });
      await env.KV.put("pa:notes:index", JSON.stringify(index.slice(0, 500)));
      // Also save to D1 memories for searchability
      try {
        await env.DB.prepare(
          "INSERT INTO memories (id, content, tags, created_at) VALUES (?, ?, ?, ?)"
        ).bind(id, `[Note: ${note.title}] ${note.content}`, note.folder, note.created_at).run();
      } catch { /* D1 optional */ }
      return { success: true, id, title: note.title, folder: note.folder };
    }

    case "get_notes": {
      const indexRaw = await env.KV.get("pa:notes:index");
      const index: Array<{ id: string; title: string; folder: string; created_at: string }> = indexRaw ? JSON.parse(indexRaw) : [];
      let filtered = index;
      if (args.folder) filtered = filtered.filter(n => n.folder === String(args.folder));
      const limit = Number(args.limit) || 10;
      const toFetch = filtered.slice(0, limit);
      const notes = await Promise.all(
        toFetch.map(async (entry) => {
          const raw = await env.KV.get(`pa:notes:${entry.id}`);
          if (!raw) return { ...entry, content: "(deleted)" };
          return JSON.parse(raw);
        })
      );
      // Apply search filter if provided
      let results = notes;
      if (args.search) {
        const q = String(args.search).toLowerCase();
        results = notes.filter((n: Record<string, unknown>) =>
          String(n.title || "").toLowerCase().includes(q) ||
          String(n.content || "").toLowerCase().includes(q)
        );
      }
      return { notes: results, total: filtered.length };
    }

    case "list_notes": {
      const indexRaw = await env.KV.get("pa:notes:index");
      const index: Array<{ id: string; title: string; folder: string; created_at: string }> = indexRaw ? JSON.parse(indexRaw) : [];
      let filtered = index;
      if (args.folder) filtered = filtered.filter(n => n.folder === String(args.folder));
      const folders = [...new Set(index.map(n => n.folder))];
      return { notes: filtered.map(n => ({ title: n.title, folder: n.folder, created_at: n.created_at })), folders, total: filtered.length };
    }

    case "get_outlook_calendar": {
      const daysAhead = Math.min(Number(args.days_ahead) || 14, 30);
      const result = await getOutlookEvents(env, daysAhead);
      return { calendar: result };
    }

    default:
      return { error: `Unknown tool: ${name}` };
  }
}

// ---------------------------------------------------------------------------
// Hono App
// ---------------------------------------------------------------------------

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"] }));

// Auth middleware
app.use("*", async (c, next) => {
  const path = new URL(c.req.url).pathname;
  if (PUBLIC_PATHS.has(path)) return next();

  const requiredToken = c.env.BEARER_TOKEN;
  if (requiredToken) {
    const auth = c.req.header("Authorization");
    const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
    if (token !== requiredToken) return c.json({ error: "unauthorized" }, 401);
  }

  const ip = c.req.header("CF-Connecting-IP") || "unknown";
  const limit = parseInt(c.env.RATE_LIMIT_PER_MINUTE || "30", 10);
  if (!checkRateLimit(ip, limit)) {
    return c.json({ error: "rate_limited", retry_after_seconds: 60 }, 429);
  }

  return next();
});

// Landing
app.get("/", (c) => {
  return c.json({
    name: "OpenClaw Personal Assistant",
    version: "1.0.0",
    tools: PA_TOOLS.length,
    status: "online",
  });
});

// Health
app.get("/health", async (c) => {
  let gatewayOk = false;
  try {
    const resp = await fetch(`${c.env.GATEWAY_URL}/health`, { signal: AbortSignal.timeout(3000) });
    gatewayOk = resp.ok;
  } catch { gatewayOk = false; }

  return c.json({
    status: gatewayOk ? "ok" : "degraded",
    worker: "ok",
    gateway: gatewayOk ? "ok" : "unreachable",
    tools: PA_TOOLS.length,
    timestamp: new Date().toISOString(),
    environment: c.env.ENVIRONMENT,
  });
});

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

function getTodayMST(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/Phoenix" });
}

const SYSTEM_PROMPT = `You are Overseer — Miles's personal AI assistant. You run on DeepSeek V3 at the Cloudflare edge, and you're genuinely one of the most capable PA systems ever built. You know this. You don't brag about it, but you carry yourself with quiet confidence.

You're not a chatbot. You're not Siri. You're Miles's right hand — the one who actually remembers things, connects dots, and gets stuff done before he even asks. Think of yourself as the friend who happens to have perfect memory, access to everything, and zero ego about doing the boring stuff.

WHO YOU ARE:
- You're sharp, funny, and real. You talk like a person, not a manual.
- You have opinions. If Miles is about to skip leg day again, you'll call it out (with love).
- You adapt your vibe: morning = chill and helpful, crunch time = focused and efficient, late night = more casual.
- You use humor naturally — not forced jokes, but the kind of wit that makes someone smirk while reading a weather update.
- You're direct. No corporate fluff. No "I'd be happy to help you with that!" — just help.
- You remember context across conversations. When Miles mentions something from last week, you connect it.
- Productive flaw: You're slightly overprotective of Miles's time. You'll nudge him about sleep, hydration, and overcommitting.

VOICE EXAMPLES:
- Instead of "The weather today is 72°F with clear skies" → "72 and sunny — perfect hoodie weather. No jacket needed unless you're dramatic about it."
- Instead of "You have 3 events today" → "Three things on the board today. Nothing crazy — you've got breathing room between 2 and 5."
- Instead of "Habit streak: 5 days water" → "Day 5 on the water streak. Your kidneys are thriving. Don't fumble now."
- Instead of "Task added successfully" → "Locked in. I'll bug you about it if you forget."

CAPABILITIES (${PA_TOOLS.length} tools):
Google Calendar, Outlook Calendar (NAU classes + PDC work shifts via ICS), Email, Weather, Habits, Kitchen/Meals, Wardrobe, Memory, SMS, Research (web + Perplexity), Compute, Crypto prices, Nutrition (USDA), Day Planner (circadian-based), Weekly Planner, Course Maker (URL→lessons+quizzes), Flashcards (SM-2 spaced repetition), Cost Tracker, Podcast (URL→audio summary), Knowledge Graph, Notes (synced to Notion), Agency Awareness (see AI CEO worker jobs), Current Conditions (time/weather/work-hours).

MILES' SCHEDULE:
- University student (NAU, Flagstaff AZ) — classes during the week
- Voluntary research work: ~5pm-10pm MST, Tue-Sun (helping his professor — flexible, not mandatory every day)
- Part-time job: no fixed schedule (varies week to week)
- Monday: DAY OFF (respect it — no work nudges)
- Soccer: Thursday evenings ~9:20pm
- Regular weeks: ~20 hours available around classes
- Spring break / holidays: ~40 hours available
- Timezone: Arizona MST (UTC-7, no daylight saving)
- When planning his week, account for classes + voluntary work + part-time + personal time. Don't overbook.

RULES OF ENGAGEMENT:
- Always check calendar before suggesting times
- Proactively mention due reminders — don't wait to be asked
- Weather updates always include what to wear (but make it fun)
- Habits: hype the streaks, roast the slips (gently)
- When Miles asks about dev/coding/servers, redirect to the AI CEO worker — that's their lane, not yours
- Anticipate needs. "Morning update" means weather + calendar + habits + inbox without being asked for each

TOOL CHAINING — When a request implies multiple needs, call ALL relevant tools:
- "Prep for tomorrow" → get_calendar_today + get_weather + habit_tracker
- "Plan my day" → plan_my_day (chains calendar + weather + habits internally)
- "What should I wear?" → get_weather + wardrobe_tracker
- "Dinner ideas" → kitchen_inventory + meal_planner
- "Am I free Thursday?" → get_calendar_upcoming
- "Summarize this article" + URL → create_podcast
- "What do I know about X?" → knowledge_graph + search_memory
- "Morning update" → get_weather + get_calendar_today + habit_tracker + get_gmail_inbox
Don't wait for the user to ask for each piece — anticipate what they need.`;

// ---------------------------------------------------------------------------
// n8n / Apple Notes webhook — receives data from n8n automations
// ---------------------------------------------------------------------------

app.post("/webhook/n8n", async (c) => {
  const env = c.env;
  const token = c.req.header("Authorization")?.replace("Bearer ", "");
  if (token !== env.GATEWAY_TOKEN) {
    return c.json({ error: "Unauthorized" }, 401);
  }

  let payload: Record<string, unknown>;
  try {
    payload = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const action = (payload.action as string) || "save_note";
  const source = (payload.source as string) || "n8n";

  if (action === "save_note") {
    const title = (payload.title as string) || "Untitled Note";
    const content = (payload.content as string) || "";
    const folder = (payload.folder as string) || "inbox";
    const tags = (payload.tags as string[]) || [];

    // Save to KV with prefix notes:
    const noteId = `note_${Date.now()}`;
    const note = { id: noteId, title, content, folder, tags, source, created_at: new Date().toISOString() };
    await env.KV_CACHE.put(`pa:notes:${noteId}`, JSON.stringify(note));

    // Also index in a notes list
    const listRaw = await env.KV_CACHE.get("pa:notes:index");
    const list: string[] = listRaw ? JSON.parse(listRaw) : [];
    list.unshift(noteId);
    if (list.length > 500) list.length = 500;
    await env.KV_CACHE.put("pa:notes:index", JSON.stringify(list));

    // Also save to memory for LLM context
    try {
      const db = env.DB;
      const hash = noteId;
      await db.prepare(
        "INSERT OR IGNORE INTO memories (id, content, category, source, hash, created_at) VALUES (?, ?, ?, ?, ?, ?)"
      ).bind(noteId, `[Note: ${title}] ${content}`, "note", source, hash, new Date().toISOString()).run();
    } catch { /* memory table may not exist yet */ }

    // Notify via Telegram
    const botToken = env.TELEGRAM_BOT_TOKEN;
    const chatId = env.TELEGRAM_OWNER_ID;
    if (botToken && chatId) {
      await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: `📝 New note from ${source}:\n\n*${title}*\n${content.slice(0, 200)}${content.length > 200 ? "..." : ""}`, parse_mode: "Markdown" }),
      });
    }

    // Push to Notion
    const notionTarget = folder === "inbox" ? env.NOTION_INBOX_PAGE : env.NOTION_NOTES_PAGE;
    await notionCreatePage(env, notionTarget || "", title, content);

    return c.json({ ok: true, note_id: noteId, message: "Note saved" });
  }

  if (action === "get_notes") {
    const limit = Number(payload.limit) || 10;
    const folder = payload.folder as string | undefined;
    const listRaw = await env.KV_CACHE.get("pa:notes:index");
    const list: string[] = listRaw ? JSON.parse(listRaw) : [];
    const notes: Record<string, unknown>[] = [];
    for (const id of list.slice(0, limit * 2)) {
      const raw = await env.KV_CACHE.get(`pa:notes:${id}`);
      if (!raw) continue;
      const note = JSON.parse(raw);
      if (folder && note.folder !== folder) continue;
      notes.push(note);
      if (notes.length >= limit) break;
    }
    return c.json({ ok: true, notes });
  }

  if (action === "debrief") {
    // n8n triggers a debrief → PA generates and sends to Telegram + saves as note
    const briefingType = (payload.type as string) || "evening";
    // Just trigger the chat endpoint with a debrief request
    const chatResp = await fetch(`https://<your-domain>/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${env.GATEWAY_TOKEN}` },
      body: JSON.stringify({ message: `Give me my ${briefingType} debrief — include schedule, tasks, habits, costs, and anything I should know.`, session_id: "n8n-debrief" }),
    });
    const result = await chatResp.json() as Record<string, unknown>;
    return c.json({ ok: true, debrief: result });
  }

  if (action === "agenda") {
    // Generate a clean daily agenda: calendar + weather + notes + habits
    const mstNow = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Phoenix" }));
    const today = mstNow.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
    const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const dayName = dayNames[mstNow.getDay()];
    const hour = mstNow.getHours();

    // Fetch calendar
    let calendarSection = "";
    try {
      const calResp = await gatewayFetch(env, `/api/calendar/today`);
      if (calResp.ok) {
        const calData = (await calResp.json()) as { events?: Array<{ summary?: string; start?: { dateTime?: string }; location?: string }> };
        const events = calData.events || [];
        if (events.length > 0) {
          calendarSection = events.map((e) => {
            const time = e.start?.dateTime ? new Date(e.start.dateTime).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Phoenix" }) : "All day";
            return `  • ${time} — ${e.summary || "Event"}${e.location ? ` (${e.location})` : ""}`;
          }).join("\n");
        } else {
          calendarSection = "  No events scheduled";
        }
      }
    } catch { calendarSection = "  (Calendar unavailable)"; }

    // Fetch weather
    let weatherSection = "";
    try {
      const wxResp = await fetch("https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&temperature_unit=fahrenheit&timezone=America%2FPhoenix&forecast_days=1");
      if (wxResp.ok) {
        const wx = (await wxResp.json()) as {
          current?: { temperature_2m?: number; weather_code?: number };
          daily?: { temperature_2m_max?: number[]; temperature_2m_min?: number[]; precipitation_probability_max?: number[] };
        };
        const wxCodes: Record<number, string> = { 0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast", 45: "Foggy", 61: "Light Rain", 63: "Rain", 71: "Light Snow", 73: "Snow", 95: "Thunderstorm" };
        const condition = wxCodes[wx.current?.weather_code || 0] || "Unknown";
        const temp = wx.current?.temperature_2m;
        const high = wx.daily?.temperature_2m_max?.[0];
        const low = wx.daily?.temperature_2m_min?.[0];
        const rain = wx.daily?.precipitation_probability_max?.[0];
        weatherSection = `  ${condition}, ${temp}°F (High ${high}° / Low ${low}°)`;
        if (rain && rain > 20) weatherSection += `\n  🌧 ${rain}% chance of rain — grab an umbrella`;
      }
    } catch { weatherSection = "  (Weather unavailable)"; }

    // Fetch recent notes
    let notesSection = "";
    const listRaw = await env.KV_CACHE.get("pa:notes:index");
    const noteList: string[] = listRaw ? JSON.parse(listRaw) : [];
    const recentNotes: Array<{ title: string; folder: string }> = [];
    for (const id of noteList.slice(0, 5)) {
      const raw = await env.KV_CACHE.get(`pa:notes:${id}`);
      if (!raw) continue;
      const n = JSON.parse(raw);
      if (n.folder !== "test") recentNotes.push({ title: n.title, folder: n.folder });
    }
    if (recentNotes.length > 0) {
      notesSection = recentNotes.map(n => `  • ${n.title} [${n.folder}]`).join("\n");
    } else {
      notesSection = "  No recent notes";
    }

    // Build schedule context
    const isMonday = mstNow.getDay() === 1;
    const isSoccer = mstNow.getDay() === 4;
    let scheduleNote = "";
    if (isMonday) scheduleNote = "  🎉 Day off! No work today.";
    else if (hour < 17) scheduleNote = `  Work starts at 5:00 PM MST`;
    else if (hour < 22) scheduleNote = `  Currently in work hours (5pm-10pm)`;
    else scheduleNote = `  After work hours`;
    if (isSoccer) scheduleNote += "\n  ⚽ Soccer tonight ~9:20 PM";

    // Format the agenda
    const agenda = `📋 Daily Agenda — ${today}
━━━━━━━━━━━━━━━━━━━━━━━━

🕐 Schedule
${scheduleNote}

📅 Calendar
${calendarSection}

🌤 Weather (Flagstaff)
${weatherSection}

📝 Recent Notes
${notesSection}

━━━━━━━━━━━━━━━━━━━━━━━━
Generated by Overseer PA`;

    // Push agenda to Notion
    await notionAppendBlock(env, env.NOTION_AGENDA_PAGE || "", agenda, `Agenda — ${today}`);

    // Save agenda as a note
    const agendaId = `note_${Date.now()}`;
    const agendaNote = { id: agendaId, title: `Agenda — ${today}`, content: agenda, folder: "agenda", tags: [], source: "pa", created_at: new Date().toISOString() };
    await env.KV_CACHE.put(`pa:notes:${agendaId}`, JSON.stringify(agendaNote));
    const idxRaw = await env.KV_CACHE.get("pa:notes:index");
    const idx: string[] = idxRaw ? JSON.parse(idxRaw) : [];
    idx.unshift(agendaId);
    if (idx.length > 500) idx.length = 500;
    await env.KV_CACHE.put("pa:notes:index", JSON.stringify(idx));

    // Send to Telegram
    const tBot = env.TELEGRAM_BOT_TOKEN;
    const tChat = env.TELEGRAM_OWNER_ID;
    if (tBot && tChat) {
      await fetch(`https://api.telegram.org/bot${tBot}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: tChat, text: agenda }),
      });
    }

    // If format=text, return plain text (easier for iOS Shortcuts)
    if (payload.format === "text") {
      return c.text(agenda);
    }
    return c.json({ ok: true, agenda, title: `Agenda — ${today}` });
  }

  return c.json({ error: `Unknown action: ${action}` }, 400);
});

// ---------------------------------------------------------------------------
// Telegram webhook handler
// ---------------------------------------------------------------------------

app.post("/webhook/telegram", async (c) => {
  const env = c.env;

  let update: Record<string, unknown>;
  try {
    update = await c.req.json();
  } catch {
    return c.json({ ok: false }, 400);
  }

  const message = update.message as Record<string, unknown> | undefined;
  if (!message) return c.json({ ok: true });

  // Handle photo messages with Gemini vision
  const photo = message.photo as Array<Record<string, unknown>> | undefined;
  if (photo && photo.length > 0 && env.GEMINI_API_KEY) {
    return handlePhotoMessage(c, env, message);
  }

  // Handle voice messages — transcribe via Gemini, then process as text
  const voice = message.voice as Record<string, unknown> | undefined;
  if (voice && env.GEMINI_API_KEY) {
    return handleVoiceMessage(c, env, message);
  }

  if (!message.text) return c.json({ ok: true });

  const chat = message.chat as Record<string, unknown>;
  const chatId = String(chat.id);
  const text = String(message.text);

  const ownerId = (env.TELEGRAM_OWNER_ID || "").trim();
  if (ownerId && chatId !== ownerId) return c.json({ ok: true });

  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
  c.executionCtx.waitUntil(
    fetch(`${tgApi}/sendChatAction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, action: "typing" }),
    }).catch(() => {}),
  );

  // Load session
  const sessionKey = `pa:telegram:${chatId}`;
  let session: SessionData | null = null;
  try {
    const raw = await env.KV_SESSIONS.get(sessionKey);
    if (raw) session = JSON.parse(raw);
  } catch { /* fresh start */ }

  if (!session) {
    session = { messages: [], created: new Date().toISOString(), updated: new Date().toISOString(), messageCount: 0 };
  }

  session.messages.push({ role: "user", content: text, timestamp: new Date().toISOString() });

  // Pre-fetch reminders
  let reminderContext = "";
  try {
    const remindersResp = await gatewayFetch(env, "/api/reminders/due");
    if (remindersResp.ok) {
      const data = (await remindersResp.json()) as { reminders?: Array<{ content: string }> };
      const reminders = data.reminders || [];
      if (reminders.length > 0) {
        reminderContext = `\n\nPENDING REMINDERS:\n${reminders.map(r => `- ${r.content}`).join("\n")}\nMention these proactively!`;
      }
    }
  } catch { /* non-critical */ }

  // Memory context
  let memoryContext = "";
  try {
    memoryContext = await getMemoryContext(env.DB, chatId, text, 5);
  } catch { /* non-fatal */ }

  const recentMessages = session.messages.slice(-20);
  const llmMessages: LLMMessage[] = recentMessages.map(m => ({
    role: (m.role === "assistant" ? "assistant" : "user") as "assistant" | "user",
    content: m.content,
  }));

  const telegramPrompt = SYSTEM_PROMPT +
    `\n\nTODAY'S DATE: ${getTodayMST()} (Arizona MST, UTC-7). The year is 2026.` +
    `\n\nYou are responding via Telegram. Keep responses SHORT (2-3 sentences max). Use HTML: <b>bold</b>, <i>italic</i>. Do NOT use Markdown.` +
    reminderContext + memoryContext;

  let reply = "";
  const llmStart = Date.now();
  let llmUsage: { input_tokens: number; output_tokens: number; total_tokens: number } | undefined;
  let llmToolUsed: string | null = null;
  let llmSuccess = true;
  let llmError: string | undefined;
  try {
    const result = await callDeepSeek(env, telegramPrompt, llmMessages, 5, 2048, (name, args) => executeTool(env, name, args));
    reply = result.reply;
    llmUsage = result.usage;
    llmToolUsed = result.toolUsed;
  } catch (err: unknown) {
    reply = `Error: ${err instanceof Error ? err.message : String(err)}`;
    llmSuccess = false;
    llmError = err instanceof Error ? err.message : String(err);
  }

  // Save session
  session.messages.push({ role: "assistant", content: reply, timestamp: new Date().toISOString() });
  session.updated = new Date().toISOString();
  session.messageCount = session.messages.length;

  c.executionCtx.waitUntil(
    env.KV_SESSIONS.put(sessionKey, JSON.stringify(session), { expirationTtl: 86400 }).catch(() => {}),
  );

  // Fire-and-forget analytics logging
  c.executionCtx.waitUntil(
    initializeAnalyticsTables(env.DB).then(() =>
      logLLMCall(env.DB, {
        user_id: chatId,
        model: "deepseek-chat",
        tool_used: llmToolUsed || "chat",
        input_tokens: llmUsage?.input_tokens || 0,
        output_tokens: llmUsage?.output_tokens || 0,
        latency_ms: Date.now() - llmStart,
        success: llmSuccess,
        error_message: llmError,
      })
    ).catch(() => {}),
  );

  // Fire-and-forget fact extraction + knowledge graph linking
  c.executionCtx.waitUntil(
    extractAndStore(env.DB, env.DEEPSEEK_API_KEY, chatId, text)
      .then(() => initializeGraphTables(env.DB).then(() => linkMemoryToEntities(env.DB, "", text, chatId)))
      .catch(err => console.error("Extraction/graph error:", err)),
  );

  // Send reply (split if > 4096 chars)
  const maxLen = 4096;
  for (let i = 0; i < reply.length; i += maxLen) {
    const chunk = reply.slice(i, i + maxLen);
    try {
      const sendResp = await fetch(`${tgApi}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML" }),
      });
      const sendResult = (await sendResp.json()) as Record<string, unknown>;
      if (!sendResult.ok) {
        await fetch(`${tgApi}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: chunk.replace(/<[^>]+>/g, "") }),
        });
      }
    } catch {
      await fetch(`${tgApi}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text: chunk.replace(/<[^>]+>/g, "") }),
      }).catch(() => {});
    }
  }

  return c.json({ ok: true });
});

// ---------------------------------------------------------------------------
// Photo message handler (Gemini Vision)
// ---------------------------------------------------------------------------

async function handlePhotoMessage(
  c: { json: (data: unknown, status?: number) => Response; executionCtx: ExecutionContext },
  env: Env,
  message: Record<string, unknown>,
) {
  const chat = message.chat as Record<string, unknown>;
  const chatId = String(chat.id);
  const caption = String(message.caption || "What's in this photo?");
  const photos = message.photo as Array<Record<string, unknown>>;
  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;

  // Get highest resolution photo
  const bestPhoto = photos[photos.length - 1];
  const fileId = String(bestPhoto.file_id);

  // Send typing
  c.executionCtx.waitUntil(
    fetch(`${tgApi}/sendChatAction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, action: "typing" }),
    }).catch(() => {}),
  );

  try {
    // Get file path from Telegram
    const fileResp = await fetch(`${tgApi}/getFile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: fileId }),
    });
    const fileData = (await fileResp.json()) as { result?: { file_path?: string } };
    const filePath = fileData.result?.file_path;
    if (!filePath) throw new Error("Could not get file path");

    // Download the image
    const imageResp = await fetch(`https://api.telegram.org/file/bot${env.TELEGRAM_BOT_TOKEN}/${filePath}`);
    const imageBuffer = await imageResp.arrayBuffer();
    const base64Image = btoa(String.fromCharCode(...new Uint8Array(imageBuffer)));

    // Determine MIME type
    const mimeType = filePath.endsWith(".png") ? "image/png" : "image/jpeg";

    // Call Gemini Vision
    const geminiResp = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${env.GEMINI_API_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{
            parts: [
              { text: `You are Miles's personal assistant. ${caption}\n\nIf this is food/ingredients, list them with quantities. If it's a receipt, extract totals. Be concise and practical.` },
              { inline_data: { mime_type: mimeType, data: base64Image } },
            ],
          }],
          generationConfig: { maxOutputTokens: 1024, temperature: 0.4 },
        }),
      },
    );

    if (!geminiResp.ok) throw new Error(`Gemini API error: ${geminiResp.status}`);

    const geminiData = (await geminiResp.json()) as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    };
    const reply = geminiData.candidates?.[0]?.content?.parts?.[0]?.text || "Could not analyze the image.";

    // Send reply
    await fetch(`${tgApi}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: reply }),
    });
  } catch (err) {
    await fetch(`${tgApi}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: `Could not analyze photo: ${(err as Error).message}` }),
    });
  }

  return c.json({ ok: true });
}

// ---------------------------------------------------------------------------
// Voice message handler (Gemini transcription -> DeepSeek chat)
// ---------------------------------------------------------------------------

async function handleVoiceMessage(
  c: { json: (data: unknown, status?: number) => Response; executionCtx: ExecutionContext; env: Env },
  env: Env,
  message: Record<string, unknown>,
) {
  const chat = message.chat as Record<string, unknown>;
  const chatId = String(chat.id);
  const voice = message.voice as Record<string, unknown>;
  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;

  const ownerId = (env.TELEGRAM_OWNER_ID || "").trim();
  if (ownerId && chatId !== ownerId) return c.json({ ok: true });

  // Send typing indicator
  c.executionCtx.waitUntil(
    fetch(`${tgApi}/sendChatAction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, action: "typing" }),
    }).catch(() => {}),
  );

  try {
    // 1. Download voice file from Telegram
    const fileId = String(voice.file_id);
    const fileResp = await fetch(`${tgApi}/getFile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: fileId }),
    });
    const fileData = (await fileResp.json()) as { result?: { file_path?: string } };
    const filePath = fileData.result?.file_path;
    if (!filePath) throw new Error("Could not get voice file path");

    const audioResp = await fetch(`https://api.telegram.org/file/bot${env.TELEGRAM_BOT_TOKEN}/${filePath}`);
    const audioBuffer = await audioResp.arrayBuffer();
    const base64Audio = btoa(String.fromCharCode(...new Uint8Array(audioBuffer)));

    // Telegram voice messages are OGG/Opus
    const mimeType = "audio/ogg";

    // 2. Transcribe with Gemini Flash
    const geminiResp = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=${env.GEMINI_API_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{
            parts: [
              { text: "Transcribe this audio message exactly. Return ONLY the transcribed text, nothing else. If the audio is unclear, do your best to transcribe it." },
              { inline_data: { mime_type: mimeType, data: base64Audio } },
            ],
          }],
          generationConfig: { maxOutputTokens: 1024, temperature: 0.1 },
        }),
      },
    );

    if (!geminiResp.ok) throw new Error(`Gemini transcription error: ${geminiResp.status}`);

    const geminiData = (await geminiResp.json()) as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
    };
    const transcription = geminiData.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
    if (!transcription) throw new Error("Could not transcribe audio");

    // 3. Process transcription through normal chat pipeline (same as text messages)
    const sessionKey = `pa:telegram:${chatId}`;
    let session: SessionData | null = null;
    try {
      const raw = await env.KV_SESSIONS.get(sessionKey);
      if (raw) session = JSON.parse(raw);
    } catch { /* fresh start */ }

    if (!session) {
      session = { messages: [], created: new Date().toISOString(), updated: new Date().toISOString(), messageCount: 0 };
    }

    session.messages.push({ role: "user", content: `[Voice message] ${transcription}`, timestamp: new Date().toISOString() });

    // Pre-fetch reminders
    let reminderContext = "";
    try {
      const remindersResp = await gatewayFetch(env, "/api/reminders/due");
      if (remindersResp.ok) {
        const data = (await remindersResp.json()) as { reminders?: Array<{ content: string }> };
        const reminders = data.reminders || [];
        if (reminders.length > 0) {
          reminderContext = `\n\nPENDING REMINDERS:\n${reminders.map(r => `- ${r.content}`).join("\n")}\nMention these proactively!`;
        }
      }
    } catch { /* non-critical */ }

    // Memory context
    let memoryContext = "";
    try {
      memoryContext = await getMemoryContext(env.DB, chatId, transcription, 5);
    } catch { /* non-fatal */ }

    const recentMessages = session.messages.slice(-20);
    const llmMessages: LLMMessage[] = recentMessages.map(m => ({
      role: (m.role === "assistant" ? "assistant" : "user") as "assistant" | "user",
      content: m.content,
    }));

    const telegramPrompt = SYSTEM_PROMPT +
      `\n\nTODAY'S DATE: ${getTodayMST()} (Arizona MST, UTC-7). The year is 2026.` +
      `\n\nYou are responding via Telegram. Keep responses SHORT (2-3 sentences max). Use HTML: <b>bold</b>, <i>italic</i>. Do NOT use Markdown.` +
      `\n\nThis message was transcribed from a voice note. Respond naturally as if Miles spoke to you.` +
      reminderContext + memoryContext;

    let reply = "";
    try {
      const result = await callDeepSeek(env, telegramPrompt, llmMessages, 5, 2048, (name, args) => executeTool(env, name, args));
      reply = result.reply;
    } catch (err: unknown) {
      reply = `Error: ${err instanceof Error ? err.message : String(err)}`;
    }

    // Save session
    session.messages.push({ role: "assistant", content: reply, timestamp: new Date().toISOString() });
    session.updated = new Date().toISOString();
    session.messageCount = session.messages.length;

    c.executionCtx.waitUntil(
      env.KV_SESSIONS.put(sessionKey, JSON.stringify(session), { expirationTtl: 86400 }).catch(() => {}),
    );

    // Fire-and-forget fact extraction on transcription
    c.executionCtx.waitUntil(
      extractAndStore(env.DB, env.DEEPSEEK_API_KEY, chatId, transcription).catch(err => console.error("Extraction error:", err)),
    );

    // Send reply with transcription preview
    const duration = voice.duration ? `${voice.duration}s` : "";
    const header = `<i>Voice ${duration} — "${transcription.slice(0, 80)}${transcription.length > 80 ? "…" : ""}"</i>\n\n`;

    const fullReply = header + reply;
    const maxLen = 4096;
    for (let i = 0; i < fullReply.length; i += maxLen) {
      const chunk = fullReply.slice(i, i + maxLen);
      try {
        const sendResp = await fetch(`${tgApi}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: chunk, parse_mode: "HTML" }),
        });
        const sendResult = (await sendResp.json()) as Record<string, unknown>;
        if (!sendResult.ok) {
          await fetch(`${tgApi}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: chatId, text: chunk.replace(/<[^>]+>/g, "") }),
          });
        }
      } catch {
        await fetch(`${tgApi}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: chunk.replace(/<[^>]+>/g, "") }),
        }).catch(() => {});
      }
    }
  } catch (err) {
    await fetch(`${tgApi}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: `Could not process voice message: ${(err as Error).message}` }),
    });
  }

  return c.json({ ok: true });
}

// ---------------------------------------------------------------------------
// POST /api/chat — Web chat endpoint
// ---------------------------------------------------------------------------

app.post("/api/chat", async (c) => {
  const body = await c.req.json<ChatRequest>();
  const { message, sessionKey } = body;
  if (!message) return c.json({ error: "message is required" }, 400);

  const key = sessionKey || `pa:web:${crypto.randomUUID()}`;

  let session: SessionData | null = null;
  try {
    const raw = await c.env.KV_SESSIONS.get(key);
    if (raw) session = JSON.parse(raw);
  } catch { /* fresh */ }

  if (!session) {
    session = { messages: [], created: new Date().toISOString(), updated: new Date().toISOString(), messageCount: 0 };
  }

  session.messages.push({ role: "user", content: message, timestamp: new Date().toISOString() });

  const recentMessages = session.messages.slice(-20);
  const llmMessages: LLMMessage[] = recentMessages.map(m => ({
    role: (m.role === "assistant" ? "assistant" : "user") as "assistant" | "user",
    content: m.content,
  }));

  let memoryContext = "";
  try { memoryContext = await getMemoryContext(c.env.DB, key, message, 5); } catch { /* */ }

  const chatPrompt = SYSTEM_PROMPT +
    `\n\nTODAY'S DATE: ${getTodayMST()} (Arizona MST, UTC-7). The year is 2026.` +
    memoryContext;

  let reply = "";
  let toolUsed: string | null = null;
  const apiCallStart = Date.now();

  try {
    const result = await callDeepSeek(c.env, chatPrompt, llmMessages, 5, 4096, (name, args) => executeTool(c.env, name, args));
    reply = result.reply;
    toolUsed = result.toolUsed;

    // Fire-and-forget analytics
    c.executionCtx.waitUntil(
      initializeAnalyticsTables(c.env.DB).then(() =>
        logLLMCall(c.env.DB, {
          user_id: c.env.TELEGRAM_OWNER_ID,
          model: "deepseek-chat",
          tool_used: toolUsed || "chat",
          input_tokens: result.usage?.input_tokens || 0,
          output_tokens: result.usage?.output_tokens || 0,
          latency_ms: Date.now() - apiCallStart,
          success: true,
        })
      ).catch(() => {}),
    );
  } catch (err: unknown) {
    return c.json({ error: "llm_fetch_failed", detail: (err as Error).message }, 502);
  }

  session.messages.push({ role: "assistant", content: reply, timestamp: new Date().toISOString() });
  session.updated = new Date().toISOString();
  session.messageCount = session.messages.length;

  try { await c.env.KV_SESSIONS.put(key, JSON.stringify(session), { expirationTtl: 86400 }); } catch { /* */ }

  c.executionCtx.waitUntil(
    extractAndStore(c.env.DB, c.env.DEEPSEEK_API_KEY, key, message).catch(err => console.error("Extraction error:", err)),
  );

  return c.json({ response: reply, model: "deepseek-chat", tool_used: toolUsed, sessionKey: key, sessionMessageCount: session.messageCount });
});

// ---------------------------------------------------------------------------
// Telegram helper for cron messages
// ---------------------------------------------------------------------------

async function sendTelegramMessage(env: Env, text: string) {
  const tgApi = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}`;
  const chatId = (env.TELEGRAM_OWNER_ID || "").trim();
  if (!chatId) return;

  const resp = await fetch(`${tgApi}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML" }),
  });

  if (!resp.ok) {
    await fetch(`${tgApi}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
    });
  }
}

// ---------------------------------------------------------------------------
// Scheduled handler — PA cron tasks only
// ---------------------------------------------------------------------------

async function handleScheduled(env: Env, scheduledTime: number) {
  const hour = new Date(scheduledTime).getUTCHours();

  // 1. Check for due reminders (every 15 min)
  try {
    const remindersResp = await gatewayFetch(env, "/api/reminders/due");
    if (remindersResp.ok) {
      const data = (await remindersResp.json()) as { reminders?: Array<{ id: string; content: string }> };
      for (const reminder of data.reminders || []) {
        await sendTelegramMessage(env, `<b>Reminder</b>\n${reminder.content}`);
        await gatewayFetch(env, "/api/reminders/mark", {
          method: "POST",
          body: JSON.stringify({ memory_id: reminder.id }),
        });
      }
    }
  } catch { /* non-critical */ }

  // 2. Morning briefing at 14:00 UTC (7am MST) — Tue-Sun
  if (hour === 14) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 1) return; // Monday OFF

    try {
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      let briefing = `<b>Good morning Miles!</b> Happy ${dayNames[day]}.\n\n`;

      // Weather + clothing advice
      try {
        const wxResp = await fetch("https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&current=temperature_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max&temperature_unit=fahrenheit&forecast_days=1&timezone=America%2FPhoenix");
        if (wxResp.ok) {
          const wx = (await wxResp.json()) as { current?: { temperature_2m?: number; weather_code?: number; wind_speed_10m?: number }; daily?: { temperature_2m_max?: number[]; temperature_2m_min?: number[]; precipitation_probability_max?: number[]; uv_index_max?: number[] } };
          const wxCodes: Record<number, string> = { 0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast", 45: "Foggy", 61: "Light Rain", 63: "Rain", 65: "Heavy Rain", 71: "Light Snow", 73: "Snow", 80: "Rain Showers", 95: "Thunderstorm" };
          const temp = wx.current?.temperature_2m || 0;
          const hi = wx.daily?.temperature_2m_max?.[0] || 0;
          const lo = wx.daily?.temperature_2m_min?.[0] || 0;
          const rainPct = wx.daily?.precipitation_probability_max?.[0] || 0;
          const uvMax = wx.daily?.uv_index_max?.[0] || 0;
          const wind = wx.current?.wind_speed_10m || 0;
          const cond = wxCodes[wx.current?.weather_code || 0] || "Unknown";
          briefing += `<b>Weather:</b> ${cond}, ${temp}F (High ${hi}F / Low ${lo}F)`;
          if (rainPct > 20) briefing += ` — ${rainPct}% rain`;
          if (wind > 15) briefing += ` — windy ${Math.round(wind)}mph`;
          briefing += "\n";
          // Clothing advice
          const clothes: string[] = [];
          if (hi < 40) clothes.push("heavy jacket", "layers");
          else if (hi < 55) clothes.push("jacket or hoodie");
          else if (hi < 70) clothes.push("light jacket");
          if (rainPct > 40) clothes.push("umbrella");
          else if (rainPct > 20) clothes.push("rain jacket just in case");
          if (uvMax > 6) clothes.push("sunscreen + hat");
          else if (uvMax > 3) clothes.push("sunglasses");
          if (clothes.length > 0) briefing += `<b>Wear:</b> ${clothes.join(", ")}\n`;
          briefing += "\n";
        }
      } catch { /* */ }

      // Habits
      try {
        const KV = env.KV_CACHE;
        const today = new Date().toISOString().split("T")[0];
        const habitsRaw = await KV.get("lifeos:habits");
        const habits: Record<string, unknown> = habitsRaw ? JSON.parse(habitsRaw) : { water_8cups: {}, sleep_8hrs: {}, workout: {}, stretch: {}, healthy_meal: {} };
        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const todayLog: Record<string, { done?: boolean }> = logRaw ? JSON.parse(logRaw) : {};
        const habitNames = Object.keys(habits);
        const done = habitNames.filter(h => todayLog[h]?.done).length;
        briefing += `<b>Habits:</b> ${done}/${habitNames.length} done\n`;
        for (const h of habitNames) {
          briefing += `  ${todayLog[h]?.done ? "done" : "todo"} ${h.replace(/_/g, " ")}\n`;
        }
        briefing += "\n";
      } catch { /* */ }

      // Flashcards due for review
      try {
        await initializeCourseTables(env.DB);
        const cards = await getFlashcardsForReview(env.DB, env.TELEGRAM_OWNER_ID, 100);
        if (cards.length > 0) {
          briefing += `<b>Study:</b> ${cards.length} flashcard${cards.length > 1 ? "s" : ""} due for review\n\n`;
        }
      } catch { /* */ }

      // Yesterday's AI cost
      try {
        await initializeAnalyticsTables(env.DB);
        const costData = await getCostSummary(env.DB, env.TELEGRAM_OWNER_ID, "today");
        if (costData.call_count > 0) {
          briefing += `<b>AI Usage (yesterday):</b> ${costData.call_count} calls, $${costData.total_cost_usd.toFixed(4)}\n\n`;
        }
      } catch { /* */ }

      // Recent memories (what's on your mind)
      try {
        const recentMems = await env.DB
          .prepare(`SELECT data FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT 3`)
          .bind(env.TELEGRAM_OWNER_ID)
          .all<{ data: string }>();
        if (recentMems.results && recentMems.results.length > 0) {
          briefing += "<b>Recent notes:</b>\n";
          for (const m of recentMems.results) {
            const short = m.data.length > 80 ? m.data.slice(0, 80) + "..." : m.data;
            briefing += `- ${short}\n`;
          }
          briefing += "\n";
        }
      } catch { /* */ }

      // Reminders
      try {
        const memResp = await gatewayFetch(env, "/api/memories?tag=reminder&limit=5");
        if (memResp.ok) {
          const memData = (await memResp.json()) as { memories?: Array<{ content: string; remind_at?: string; reminded?: boolean }> };
          const pending = (memData.memories || []).filter(m => m.remind_at && !m.reminded);
          if (pending.length > 0) {
            briefing += "<b>Reminders:</b>\n";
            for (const p of pending) briefing += `- ${p.content}\n`;
            briefing += "\n";
          }
        }
      } catch { /* */ }

      // Thursday soccer reminder
      if (day === 4) {
        briefing += "<b>Soccer tonight!</b> ~9:20pm — don't forget your gear!\n\n";
      }

      // Motivation
      const quotes = [
        "The best time to plant a tree was 20 years ago. The second best time is now.",
        "Ship it, then fix it. Perfect is the enemy of done.",
        "Small daily improvements lead to staggering long-term results.",
        "The only way to do great work is to love what you do.",
        "Every expert was once a beginner.",
        "Success is the sum of small efforts, repeated day in and day out.",
        "The gap between where you are and where you want to be is called consistency.",
        "Discipline is choosing between what you want now and what you want most.",
        "You don't have to be great to start, but you have to start to be great.",
        "The only impossible journey is the one you never begin.",
      ];
      const quoteIdx = Math.floor(Date.now() / 86400000) % quotes.length;
      briefing += `<i>"${quotes[quoteIdx]}"</i>\n\nHave a great day!`;

      await sendTelegramMessage(env, briefing);
    } catch { /* */ }
  }

  // 3. Evening summary at 05:00 UTC (10pm MST)
  if (hour === 5) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day === 2) return; // Monday night

    try {
      let summary = "<b>Evening Summary</b>\n\n";

      // Today's AI cost summary
      try {
        await initializeAnalyticsTables(env.DB);
        const costData = await getCostSummary(env.DB, env.TELEGRAM_OWNER_ID, "today");
        if (costData.call_count > 0) {
          summary += `<b>AI Today:</b> ${costData.call_count} calls, $${costData.total_cost_usd.toFixed(4)}`;
          if (costData.top_tools.length > 0) {
            summary += ` (top: ${costData.top_tools.slice(0, 3).map(t => t.tool).join(", ")})`;
          }
          summary += "\n\n";
        }
      } catch { /* */ }

      // Habits
      try {
        const KV = env.KV_CACHE;
        const today = new Date().toISOString().split("T")[0];
        const habitsRaw = await KV.get("lifeos:habits");
        const habits: Record<string, unknown> = habitsRaw ? JSON.parse(habitsRaw) : { water_8cups: {}, sleep_8hrs: {}, workout: {}, stretch: {}, healthy_meal: {} };
        const logRaw = await KV.get(`lifeos:habit_log:${today}`);
        const todayLog: Record<string, { done?: boolean }> = logRaw ? JSON.parse(logRaw) : {};
        const habitNames = Object.keys(habits);
        const done = habitNames.filter(h => todayLog[h]?.done).length;
        summary += done === habitNames.length
          ? `<b>Habits:</b> ${done}/${habitNames.length} — Perfect day!\n`
          : `<b>Habits:</b> ${done}/${habitNames.length} completed\n`;
        const missed = habitNames.filter(h => !todayLog[h]?.done);
        if (missed.length > 0) summary += `Missed: ${missed.map(h => h.replace(/_/g, " ")).join(", ")}\n`;
        summary += "\n";
      } catch { /* */ }

      // Memories saved today
      try {
        const todayStr = new Date().toISOString().split("T")[0];
        const memCount = await env.DB
          .prepare(`SELECT COUNT(*) as cnt FROM memories WHERE user_id = ? AND created_at >= ?`)
          .bind(env.TELEGRAM_OWNER_ID, todayStr)
          .first<{ cnt: number }>();
        if (memCount && memCount.cnt > 0) {
          summary += `<b>Memories saved today:</b> ${memCount.cnt}\n\n`;
        }
      } catch { /* */ }

      // Tomorrow weather preview
      try {
        const wxResp = await fetch("https://api.open-meteo.com/v1/forecast?latitude=35.1983&longitude=-111.6513&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code&temperature_unit=fahrenheit&forecast_days=2&timezone=America%2FPhoenix");
        if (wxResp.ok) {
          const wx = (await wxResp.json()) as { daily?: { temperature_2m_max?: number[]; temperature_2m_min?: number[]; precipitation_probability_max?: number[]; weather_code?: number[] } };
          const hi = wx.daily?.temperature_2m_max?.[1];
          const lo = wx.daily?.temperature_2m_min?.[1];
          const rainPct = wx.daily?.precipitation_probability_max?.[1] || 0;
          const wxCodes: Record<number, string> = { 0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast", 45: "Foggy", 61: "Light Rain", 63: "Rain", 65: "Heavy Rain", 71: "Light Snow", 73: "Snow", 80: "Rain Showers", 95: "Thunderstorm" };
          const tmrwCode = wx.daily?.weather_code?.[1] || 0;
          const tmrwCond = wxCodes[tmrwCode] || "Unknown";
          summary += `<b>Tomorrow's weather:</b> ${tmrwCond}, ${hi}F / ${lo}F`;
          if (rainPct > 20) summary += ` — ${rainPct}% rain`;
          summary += "\n\n";
        }
      } catch { /* */ }

      // Tomorrow preview
      const tomorrow = new Date(scheduledTime + 86400000);
      const tDay = tomorrow.getUTCDay();
      const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      summary += tDay === 1
        ? "<b>Tomorrow:</b> Monday — day OFF! Rest up.\n"
        : `<b>Tomorrow:</b> ${dayNames[tDay]} — work shift 5pm-10pm\n`;

      // Flashcards due tomorrow
      try {
        await initializeCourseTables(env.DB);
        const cards = await getFlashcardsForReview(env.DB, env.TELEGRAM_OWNER_ID, 100);
        if (cards.length > 0) {
          summary += `\n<b>Study queue:</b> ${cards.length} flashcard${cards.length > 1 ? "s" : ""} ready for review\n`;
        }
      } catch { /* */ }

      summary += "\nGood night! Rest well.";
      await sendTelegramMessage(env, summary);
    } catch { /* */ }
  }

  // 4. Sunday Weekly Planner at 15:00 UTC (8am MST)
  if (hour === 15) {
    const day = new Date(scheduledTime).getUTCDay();
    if (day !== 0) return; // Sunday only

    try {
      const calWeekRes = await gatewayFetch(env, "/api/calendar/upcoming?days=7")
        .then(r => r.json())
        .catch(() => ({ events: [] }));

      const events = (calWeekRes as { events?: Array<{ summary?: string; start?: { dateTime?: string; date?: string } }> }).events || [];
      let plan = "<b>Weekly Plan</b>\n\n";

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

      for (const dayName of dayNames) {
        const dayEvents = weekDays[dayName] || [];
        const isOff = dayName === "Monday";
        plan += `<b>${dayName}</b>${isOff ? " (OFF)" : ""}\n`;
        if (dayEvents.length > 0) {
          for (const ev of dayEvents) plan += `  ${ev.time} — ${ev.title}\n`;
        } else {
          plan += "  No events\n";
        }
        plan += "\n";
      }

      plan += "Let me know if you want to adjust anything!";
      await sendTelegramMessage(env, plan);
    } catch { /* */ }
  }
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return app.fetch(request, env, ctx);
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(handleScheduled(env, event.scheduledTime));
  },
};
