import type { OpenClawConfig } from "../config/config.js";
import { fetchWithSsrFGuard } from "../infra/net/fetch-guard.js";
import { extractReadableContent } from "./tools/web-fetch-utils.js";
import { DEFAULT_TIMEOUT_SECONDS, readResponseText, withTimeout } from "./tools/web-shared.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ResearchSource = {
  url: string;
  title?: string;
  snippet: string;
};

export type ResearchResult = {
  query: string;
  summary: string;
  sources: ResearchSource[];
  fetchedUrls: number;
  totalSearchResults: number;
  tookMs: number;
  model: string;
  cached: boolean;
};

export type ResearchOptions = {
  /** Maximum number of search results to request. Default: 5. */
  maxSearchResults?: number;
  /** Maximum number of URLs to fetch in parallel. Default: 3, max: 3. */
  maxParallelFetches?: number;
  /** Maximum characters to extract per page. Default: 12000. */
  maxCharsPerPage?: number;
  /** Maximum characters for the final summary. Default: 4000. */
  maxSummaryChars?: number;
  /** Timeout in seconds for each network request. Default: 30. */
  timeoutSeconds?: number;
  /** Two-letter country code for regional results (e.g. "US", "DE"). */
  country?: string;
  /** Language code for search results (e.g. "en", "de"). */
  searchLang?: string;
  /** OpenClaw config for API key resolution. */
  config?: OpenClawConfig;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const RESEARCH_MODEL = "claude-haiku-4-5-20250929";
const BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search";
const DEFAULT_MAX_SEARCH_RESULTS = 5;
const DEFAULT_MAX_PARALLEL_FETCHES = 3;
const MAX_PARALLEL_FETCHES_CAP = 3;
const DEFAULT_MAX_CHARS_PER_PAGE = 12_000;
const DEFAULT_MAX_SUMMARY_CHARS = 4_000;
const DEFAULT_USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

type SearchHit = {
  title: string;
  url: string;
  description: string;
};

function resolveSearchApiKey(config?: OpenClawConfig): string | undefined {
  const fromConfig = config?.tools?.web?.search;
  const configKey =
    fromConfig && typeof fromConfig === "object" && "apiKey" in fromConfig
      ? String(fromConfig.apiKey ?? "").trim()
      : "";
  const envKey = (process.env.BRAVE_API_KEY ?? "").trim();
  return configKey || envKey || undefined;
}

function resolveAnthropicApiKey(config?: OpenClawConfig): string | undefined {
  const envKey = (process.env.ANTHROPIC_API_KEY ?? "").trim();
  if (envKey) {
    return envKey;
  }
  const agents = config?.agents;
  if (agents && typeof agents === "object") {
    for (const agent of Object.values(agents)) {
      if (
        agent &&
        typeof agent === "object" &&
        "apiKeyEnv" in agent &&
        agent.apiKeyEnv === "ANTHROPIC_API_KEY"
      ) {
        const resolved = process.env.ANTHROPIC_API_KEY?.trim();
        if (resolved) {
          return resolved;
        }
      }
    }
  }
  return undefined;
}

function clampNumber(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number,
): number {
  const raw = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.max(min, Math.min(max, Math.floor(raw)));
}

async function braveSearch(params: {
  query: string;
  count: number;
  apiKey: string;
  timeoutSeconds: number;
  country?: string;
  searchLang?: string;
}): Promise<SearchHit[]> {
  const url = new URL(BRAVE_SEARCH_ENDPOINT);
  url.searchParams.set("q", params.query);
  url.searchParams.set("count", String(params.count));
  if (params.country) {
    url.searchParams.set("country", params.country);
  }
  if (params.searchLang) {
    url.searchParams.set("search_lang", params.searchLang);
  }

  const res = await fetch(url.toString(), {
    method: "GET",
    headers: {
      Accept: "application/json",
      "X-Subscription-Token": params.apiKey,
    },
    signal: withTimeout(undefined, params.timeoutSeconds * 1000),
  });

  if (!res.ok) {
    const detail = await readResponseText(res);
    throw new Error(`Brave Search API error (${res.status}): ${detail || res.statusText}`);
  }

  const data = (await res.json()) as {
    web?: { results?: Array<{ title?: string; url?: string; description?: string }> };
  };
  const results = data.web?.results ?? [];
  return results.map((r) => ({
    title: r.title ?? "",
    url: r.url ?? "",
    description: r.description ?? "",
  }));
}

async function fetchPageContent(params: {
  url: string;
  maxChars: number;
  timeoutSeconds: number;
}): Promise<{ title?: string; text: string } | null> {
  try {
    const result = await fetchWithSsrFGuard({
      url: params.url,
      maxRedirects: 3,
      timeoutMs: params.timeoutSeconds * 1000,
      init: {
        headers: {
          Accept: "*/*",
          "User-Agent": DEFAULT_USER_AGENT,
          "Accept-Language": "en-US,en;q=0.9",
        },
      },
    });
    const res = result.response;
    const release = result.release;
    try {
      if (!res.ok) {
        return null;
      }
      const contentType = res.headers.get("content-type") ?? "";
      const body = await readResponseText(res);
      if (!body) {
        return null;
      }

      if (contentType.includes("text/html")) {
        const readable = await extractReadableContent({
          html: body,
          url: result.finalUrl,
          extractMode: "text",
        });
        if (readable?.text) {
          return {
            title: readable.title,
            text: readable.text.slice(0, params.maxChars),
          };
        }
        return null;
      }

      return { text: body.slice(0, params.maxChars) };
    } finally {
      if (release) {
        await release();
      }
    }
  } catch {
    return null;
  }
}

async function summarizeWithHaiku(params: {
  query: string;
  pages: Array<{ url: string; title?: string; text: string }>;
  maxSummaryChars: number;
  apiKey: string;
  timeoutSeconds: number;
}): Promise<string> {
  const contextBlocks = params.pages.map((page, idx) => {
    const header = page.title
      ? `[${idx + 1}] ${page.title} (${page.url})`
      : `[${idx + 1}] ${page.url}`;
    return `${header}\n${page.text}`;
  });

  const systemPrompt = [
    "You are a research assistant. Summarize the provided web page content to answer the user's query.",
    "Include source citations using [N] notation referencing the numbered sources.",
    "Be concise and factual. Focus on directly answering the query.",
    `Keep your response under ${params.maxSummaryChars} characters.`,
  ].join(" ");

  const userMessage = [`QUERY: ${params.query}`, "", "SOURCES:", ...contextBlocks].join("\n");

  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": params.apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: RESEARCH_MODEL,
      max_tokens: 1024,
      system: systemPrompt,
      messages: [{ role: "user", content: userMessage }],
    }),
    signal: withTimeout(undefined, params.timeoutSeconds * 1000),
  });

  if (!res.ok) {
    const detail = await readResponseText(res);
    throw new Error(`Anthropic API error (${res.status}): ${detail || res.statusText}`);
  }

  const data = (await res.json()) as {
    content?: Array<{ type?: string; text?: string }>;
  };
  const textBlock = data.content?.find((b) => b.type === "text");
  return textBlock?.text ?? "No summary generated.";
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function researchAgent(
  query: string,
  options?: ResearchOptions,
): Promise<ResearchResult> {
  const start = Date.now();

  const maxSearchResults = clampNumber(
    options?.maxSearchResults,
    DEFAULT_MAX_SEARCH_RESULTS,
    1,
    10,
  );
  const maxParallelFetches = clampNumber(
    options?.maxParallelFetches,
    DEFAULT_MAX_PARALLEL_FETCHES,
    1,
    MAX_PARALLEL_FETCHES_CAP,
  );
  const maxCharsPerPage = clampNumber(
    options?.maxCharsPerPage,
    DEFAULT_MAX_CHARS_PER_PAGE,
    500,
    50_000,
  );
  const maxSummaryChars = clampNumber(
    options?.maxSummaryChars,
    DEFAULT_MAX_SUMMARY_CHARS,
    200,
    16_000,
  );
  const timeoutSeconds = clampNumber(options?.timeoutSeconds, DEFAULT_TIMEOUT_SECONDS, 5, 120);

  const searchApiKey = resolveSearchApiKey(options?.config);
  if (!searchApiKey) {
    throw new Error(
      "Research agent requires a Brave Search API key. Set BRAVE_API_KEY or configure tools.web.search.apiKey.",
    );
  }

  const anthropicApiKey = resolveAnthropicApiKey(options?.config);
  if (!anthropicApiKey) {
    throw new Error(
      "Research agent requires an Anthropic API key for summarization. Set ANTHROPIC_API_KEY.",
    );
  }

  // Step 1: Search the web
  const searchResults = await braveSearch({
    query,
    count: maxSearchResults,
    apiKey: searchApiKey,
    timeoutSeconds,
    country: options?.country,
    searchLang: options?.searchLang,
  });

  if (searchResults.length === 0) {
    return {
      query,
      summary: "No search results found for this query.",
      sources: [],
      fetchedUrls: 0,
      totalSearchResults: 0,
      tookMs: Date.now() - start,
      model: RESEARCH_MODEL,
      cached: false,
    };
  }

  // Step 2: Fetch top URLs in parallel (capped at maxParallelFetches)
  const urlsToFetch = searchResults.slice(0, maxParallelFetches);
  const fetchPromises = urlsToFetch.map((hit) =>
    fetchPageContent({
      url: hit.url,
      maxChars: maxCharsPerPage,
      timeoutSeconds,
    }).then((content) => (content ? { url: hit.url, ...content } : null)),
  );

  const fetchedPages = (await Promise.all(fetchPromises)).filter(
    (page): page is { url: string; title?: string; text: string } => page !== null,
  );

  // If no pages could be fetched, fall back to search snippets
  const pagesToSummarize =
    fetchedPages.length > 0
      ? fetchedPages
      : searchResults.slice(0, maxParallelFetches).map((hit) => ({
          url: hit.url,
          title: hit.title,
          text: hit.description,
        }));

  // Step 3: Summarize with Haiku
  const summary = await summarizeWithHaiku({
    query,
    pages: pagesToSummarize,
    maxSummaryChars,
    apiKey: anthropicApiKey,
    timeoutSeconds,
  });

  // Step 4: Build sources list from all search results
  const sources: ResearchSource[] = searchResults.map((hit) => ({
    url: hit.url,
    title: hit.title || undefined,
    snippet: hit.description,
  }));

  return {
    query,
    summary,
    sources,
    fetchedUrls: fetchedPages.length,
    totalSearchResults: searchResults.length,
    tookMs: Date.now() - start,
    model: RESEARCH_MODEL,
    cached: false,
  };
}
