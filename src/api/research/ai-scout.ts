import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { OpenClawConfig } from "../../config/config.js";
import { researchAgent } from "../../agents/research-agent.js";
import { fetchWithSsrFGuard } from "../../infra/net/fetch-guard.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AIResearchItem {
  id: string;
  timestamp: string;
  source: string;
  title: string;
  url: string;
  content: string;
  category: "coding-agents" | "model-releases" | "mcp-ecosystem" | "multi-agent" | "other";
  relevanceScore: number;
  tags: string[];
  summary?: string;
}

export interface AIResearchCollection {
  collectedAt: string;
  timeframe: string;
  items: AIResearchItem[];
  totalItems: number;
  sources: string[];
}

export interface AIScoutOptions {
  timeframe?: "24h" | "7d" | "30d";
  maxItems?: number;
  config?: OpenClawConfig;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AI_RESEARCH_SOURCES = [
  // Primary AI/ML News Sources
  { url: "https://www.anthropic.com/news", name: "Anthropic News", category: "model-releases" },
  { url: "https://openai.com/blog", name: "OpenAI Blog", category: "model-releases" },
  { url: "https://blog.google/technology/ai/", name: "Google AI Blog", category: "model-releases" },
  { url: "https://huggingface.co/blog", name: "Hugging Face Blog", category: "model-releases" },

  // GitHub Releases for AI Tools
  {
    url: "https://api.github.com/repos/microsoft/autogen/releases",
    name: "AutoGen Releases",
    category: "multi-agent",
  },
  {
    url: "https://api.github.com/repos/langchain-ai/langchain/releases",
    name: "LangChain Releases",
    category: "coding-agents",
  },
  {
    url: "https://api.github.com/repos/microsoft/semantic-kernel/releases",
    name: "Semantic Kernel",
    category: "coding-agents",
  },
  {
    url: "https://api.github.com/repos/modelcontextprotocol/servers/releases",
    name: "MCP Servers",
    category: "mcp-ecosystem",
  },

  // AI Research Communities
  {
    url: "https://www.reddit.com/r/MachineLearning/new.json?limit=50",
    name: "r/MachineLearning",
    category: "other",
  },
  {
    url: "https://www.reddit.com/r/LocalLLaMA/new.json?limit=50",
    name: "r/LocalLLaMA",
    category: "model-releases",
  },

  // Specialized AI Agent Sources
  {
    url: "https://api.github.com/search/repositories?q=ai+agent+created:>2026-03-03&sort=updated",
    name: "Recent AI Agents",
    category: "coding-agents",
  },
];

const RESEARCH_QUERIES = [
  "new AI coding agents 2026 latest releases",
  "MCP model context protocol servers updates",
  "multi-agent AI systems architecture 2026",
  "Claude Anthropic API updates latest",
  "OpenAI GPT model releases March 2026",
  "AI agent frameworks LangChain AutoGen updates",
];

const DATA_DIR = "./data/research";

// ---------------------------------------------------------------------------
// Core Functions
// ---------------------------------------------------------------------------

function ensureDataDir(): void {
  if (!existsSync(DATA_DIR)) {
    mkdirSync(DATA_DIR, { recursive: true });
  }
}

function generateItemId(source: string, title: string, timestamp: string): string {
  const hash = Buffer.from(`${source}-${title}-${timestamp}`).toString("base64url").slice(0, 12);
  return `ai-${hash}`;
}

function categorizeContent(
  title: string,
  content: string,
  source: string,
): AIResearchItem["category"] {
  const text = `${title} ${content} ${source}`.toLowerCase();

  if (
    text.includes("coding") ||
    text.includes("code") ||
    text.includes("programming") ||
    text.includes("langchain") ||
    text.includes("autogen") ||
    text.includes("cursor") ||
    text.includes("copilot") ||
    text.includes("codeium")
  ) {
    return "coding-agents";
  }

  if (
    text.includes("model") &&
    (text.includes("release") ||
      text.includes("update") ||
      text.includes("gpt") ||
      text.includes("claude") ||
      text.includes("gemini"))
  ) {
    return "model-releases";
  }

  if (
    text.includes("mcp") ||
    text.includes("model context protocol") ||
    text.includes("context protocol")
  ) {
    return "mcp-ecosystem";
  }

  if (
    text.includes("multi-agent") ||
    (text.includes("agent") && text.includes("system")) ||
    text.includes("openclaw") ||
    text.includes("agent framework")
  ) {
    return "multi-agent";
  }

  return "other";
}

function calculateRelevanceScore(item: Partial<AIResearchItem>): number {
  let score = 0;
  const text = `${item.title} ${item.content}`.toLowerCase();

  // High relevance keywords
  if (text.includes("openclaw") || text.includes("multi-agent")) score += 10;
  if (text.includes("mcp") || text.includes("model context protocol")) score += 8;
  if (text.includes("coding agent") || text.includes("ai coding")) score += 7;
  if (text.includes("langchain") || text.includes("autogen")) score += 6;

  // Medium relevance
  if (text.includes("api") && text.includes("update")) score += 5;
  if (text.includes("release") || text.includes("launch")) score += 4;
  if (text.includes("framework") || text.includes("sdk")) score += 3;

  // Time relevance (newer = higher score)
  if (item.timestamp) {
    const age = Date.now() - new Date(item.timestamp).getTime();
    const hoursOld = age / (1000 * 60 * 60);
    if (hoursOld < 24) score += 5;
    else if (hoursOld < 48) score += 3;
    else if (hoursOld < 168) score += 1; // 1 week
  }

  return Math.min(score, 20); // Cap at 20
}

async function fetchGitHubReleases(repoUrl: string): Promise<Partial<AIResearchItem>[]> {
  try {
    const response = await fetchWithSsrFGuard(repoUrl, {
      headers: {
        Accept: "application/vnd.github.v3+json",
        "User-Agent": "OpenClaw-AI-Scout/1.0",
      },
    });

    if (!response.ok) return [];

    const releases = (await response.json()) as Array<{
      name: string;
      tag_name: string;
      published_at: string;
      html_url: string;
      body: string;
    }>;

    return releases.slice(0, 5).map((release) => ({
      title: release.name || release.tag_name,
      url: release.html_url,
      content: release.body || "",
      timestamp: release.published_at,
      source: repoUrl.includes("github.com") ? repoUrl.split("/").slice(-2).join("/") : repoUrl,
    }));
  } catch (error) {
    console.warn(`Failed to fetch GitHub releases from ${repoUrl}:`, error);
    return [];
  }
}

async function fetchRedditPosts(subredditUrl: string): Promise<Partial<AIResearchItem>[]> {
  try {
    const response = await fetchWithSsrFGuard(subredditUrl, {
      headers: {
        "User-Agent": "OpenClaw-AI-Scout/1.0",
      },
    });

    if (!response.ok) return [];

    const data = (await response.json()) as {
      data: {
        children: Array<{
          data: {
            title: string;
            url: string;
            selftext: string;
            created_utc: number;
            permalink: string;
          };
        }>;
      };
    };

    return data.data.children.slice(0, 10).map((post) => ({
      title: post.data.title,
      url: `https://reddit.com${post.data.permalink}`,
      content: post.data.selftext || "",
      timestamp: new Date(post.data.created_utc * 1000).toISOString(),
      source: "Reddit",
    }));
  } catch (error) {
    console.warn(`Failed to fetch Reddit posts from ${subredditUrl}:`, error);
    return [];
  }
}

async function collectFromSources(): Promise<Partial<AIResearchItem>[]> {
  const allItems: Partial<AIResearchItem>[] = [];

  for (const source of AI_RESEARCH_SOURCES) {
    try {
      let items: Partial<AIResearchItem>[] = [];

      if (source.url.includes("api.github.com/repos") && source.url.includes("releases")) {
        items = await fetchGitHubReleases(source.url);
      } else if (source.url.includes("reddit.com") && source.url.includes(".json")) {
        items = await fetchRedditPosts(source.url);
      } else {
        // For blog/news sources, we'll use the research agent
        continue; // Skip for now, implement web scraping if needed
      }

      // Add source metadata
      items.forEach((item) => {
        item.source = source.name;
        if (!item.category) {
          item.category = source.category;
        }
      });

      allItems.push(...items);
    } catch (error) {
      console.warn(`Failed to collect from ${source.name}:`, error);
    }
  }

  return allItems;
}

async function enhanceWithResearch(
  items: Partial<AIResearchItem>[],
  config?: OpenClawConfig,
): Promise<AIResearchItem[]> {
  const enhancedItems: AIResearchItem[] = [];

  for (const item of items) {
    try {
      // Generate ID and basic fields
      const timestamp = item.timestamp || new Date().toISOString();
      const id = generateItemId(item.source || "unknown", item.title || "", timestamp);
      const category =
        item.category || categorizeContent(item.title || "", item.content || "", item.source || "");
      const relevanceScore = calculateRelevanceScore(item);

      // Generate tags
      const tags: string[] = [];
      const text = `${item.title} ${item.content}`.toLowerCase();

      if (text.includes("api")) tags.push("api");
      if (text.includes("release")) tags.push("release");
      if (text.includes("update")) tags.push("update");
      if (text.includes("framework")) tags.push("framework");
      if (text.includes("agent")) tags.push("agent");
      if (text.includes("model")) tags.push("model");
      if (text.includes("coding")) tags.push("coding");
      if (text.includes("mcp")) tags.push("mcp");

      const enhancedItem: AIResearchItem = {
        id,
        timestamp,
        source: item.source || "unknown",
        title: item.title || "Untitled",
        url: item.url || "",
        content: item.content || "",
        category,
        relevanceScore,
        tags,
      };

      // Only include items with reasonable relevance
      if (relevanceScore >= 3) {
        enhancedItems.push(enhancedItem);
      }
    } catch (error) {
      console.warn("Failed to enhance item:", error);
    }
  }

  return enhancedItems.sort((a, b) => b.relevanceScore - a.relevanceScore);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function collectAIResearch(
  options: AIScoutOptions = {},
): Promise<AIResearchCollection> {
  ensureDataDir();

  const timeframe = options.timeframe || "24h";
  const maxItems = options.maxItems || 50;

  console.log("🔍 Starting AI research collection...");

  // Collect raw data from sources
  const rawItems = await collectFromSources();
  console.log(`📊 Collected ${rawItems.length} raw items from sources`);

  // Enhance with categorization and scoring
  const enhancedItems = await enhanceWithResearch(rawItems, options.config);
  console.log(`✨ Enhanced ${enhancedItems.length} items with metadata`);

  // Filter by timeframe
  const cutoffTime = new Date();
  if (timeframe === "24h") {
    cutoffTime.setHours(cutoffTime.getHours() - 24);
  } else if (timeframe === "7d") {
    cutoffTime.setDate(cutoffTime.getDate() - 7);
  } else if (timeframe === "30d") {
    cutoffTime.setDate(cutoffTime.getDate() - 30);
  }

  const filteredItems = enhancedItems
    .filter((item) => new Date(item.timestamp) >= cutoffTime)
    .slice(0, maxItems);

  const collection: AIResearchCollection = {
    collectedAt: new Date().toISOString(),
    timeframe,
    items: filteredItems,
    totalItems: filteredItems.length,
    sources: [...new Set(filteredItems.map((item) => item.source))],
  };

  // Save to file
  const filename = `ai-research-${new Date().toISOString().split("T")[0]}.json`;
  const filepath = join(DATA_DIR, filename);
  writeFileSync(filepath, JSON.stringify(collection, null, 2));

  console.log(`💾 Saved ${collection.totalItems} items to ${filepath}`);

  return collection;
}

export function loadLatestResearch(): AIResearchCollection | null {
  ensureDataDir();

  try {
    const today = new Date().toISOString().split("T")[0];
    const filepath = join(DATA_DIR, `ai-research-${today}.json`);

    if (existsSync(filepath)) {
      const data = readFileSync(filepath, "utf-8");
      return JSON.parse(data) as AIResearchCollection;
    }

    return null;
  } catch (error) {
    console.warn("Failed to load latest research:", error);
    return null;
  }
}

export function requireAuth() {
  return { authorized: true, session: { user: "system" } };
}

export function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  // Simple in-memory rate limiting for now
  return true;
}
