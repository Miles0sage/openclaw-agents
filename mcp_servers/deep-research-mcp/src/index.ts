#!/usr/bin/env node
/**
 * Deep Research MCP Server
 *
 * Exposes multi-step autonomous research as MCP tools.
 * Reads PERPLEXITY_API_KEY from environment.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { deepResearch } from "./research-engine.js";

const server = new McpServer({
  name: "deep-research-mcp",
  version: "1.0.0",
});

function getApiKey(): string {
  const key = process.env.PERPLEXITY_API_KEY;
  if (!key) {
    throw new Error(
      "PERPLEXITY_API_KEY environment variable is required. Get one at https://www.perplexity.ai/settings/api",
    );
  }
  return key;
}

// ── Tool: deep_research ─────────────────────────────────────────────────────

server.tool(
  "deep_research",
  "Multi-step autonomous research. Decomposes a query into sub-questions, researches each in parallel via Perplexity Sonar, and synthesizes a structured Markdown report with citations.",
  {
    query: z.string().min(5).describe("The research question or topic to investigate"),
    depth: z
      .enum(["quick", "medium", "deep"])
      .default("medium")
      .describe("Research depth: quick (3 sub-questions), medium (5), deep (8)"),
    mode: z
      .enum(["general", "market", "technical", "academic", "news", "due_diligence"])
      .default("general")
      .describe("Domain mode that shapes the research focus and system prompt"),
    max_sources: z
      .number()
      .int()
      .min(0)
      .max(8)
      .default(0)
      .describe("Max API calls (0 = auto based on depth)"),
  },
  async ({ query, depth, mode, max_sources }) => {
    const apiKey = getApiKey();

    const result = await deepResearch(query, apiKey, depth, mode, max_sources);

    const sourcesSection =
      result.sources.length > 0
        ? "\n\n---\n\n## Sources\n\n" + result.sources.map((s, i) => `${i + 1}. ${s}`).join("\n")
        : "";

    const metaSection = `\n\n---\n\n**Research metadata**: ${result.metadata.mode} mode, ${result.metadata.depth} depth, ${result.metadata.subQuestions} sub-questions, ${result.metadata.sourcesFound} sources, ${result.metadata.apiCalls} API calls, ${result.metadata.estimatedCost}, ${(result.metadata.elapsedMs / 1000).toFixed(1)}s`;

    return {
      content: [
        {
          type: "text" as const,
          text: result.report + sourcesSection + metaSection,
        },
      ],
    };
  },
);

// ── Tool: quick_research ────────────────────────────────────────────────────

server.tool(
  "quick_research",
  "Quick single-query research via Perplexity Sonar. No decomposition — just asks the question and returns the answer with citations. Good for simple factual lookups.",
  {
    query: z.string().min(5).describe("The question to research"),
    model: z
      .enum(["sonar", "sonar-pro"])
      .default("sonar")
      .describe("Model to use: sonar (fast/cheap) or sonar-pro (thorough)"),
    focus: z
      .enum(["web", "academic", "news"])
      .default("web")
      .describe("Search focus area"),
  },
  async ({ query, model, focus }) => {
    const { queryPerplexity } = await import("./perplexity.js");
    const apiKey = getApiKey();

    const result = await queryPerplexity(query, apiKey, { model, focus });

    const citations =
      result.citations.length > 0
        ? "\n\n**Sources**: " + result.citations.map((c, i) => `[${i + 1}] ${c}`).join(" | ")
        : "";

    return {
      content: [
        {
          type: "text" as const,
          text: result.answer + citations,
        },
      ],
    };
  },
);

// ── Tool: research_plan ─────────────────────────────────────────────────────

server.tool(
  "research_plan",
  "Generate a research plan without executing it. Returns the sub-questions that would be investigated for a given query. Useful for previewing/approving before running deep_research.",
  {
    query: z.string().min(5).describe("The research question to plan for"),
    depth: z
      .enum(["quick", "medium", "deep"])
      .default("medium")
      .describe("Depth determines number of sub-questions: quick (3), medium (5), deep (8)"),
    mode: z
      .enum(["general", "market", "technical", "academic", "news", "due_diligence"])
      .default("general")
      .describe("Domain mode that shapes the sub-question generation"),
  },
  async ({ query, depth, mode }) => {
    const { queryPerplexity } = await import("./perplexity.js");
    const apiKey = getApiKey();

    const DOMAIN_MODES: Record<string, { focus: "web" | "academic" | "news"; subQHint: string }> = {
      general: { focus: "web", subQHint: "Break into logical sub-topics covering different angles." },
      market: { focus: "web", subQHint: "Cover: market size, key players, pricing models, recent trends, growth drivers, risks." },
      technical: { focus: "web", subQHint: "Cover: architecture, performance benchmarks, developer experience, documentation, alternatives comparison." },
      academic: { focus: "academic", subQHint: "Cover: key papers, methodology, findings, contradictions between studies, research gaps." },
      news: { focus: "news", subQHint: "Cover: what happened, key players, timeline, different perspectives, implications." },
      due_diligence: { focus: "web", subQHint: "Cover: company overview, financials, leadership, competitors, risks, red flags, customer reviews." },
    };

    const domain = DOMAIN_MODES[mode] ?? DOMAIN_MODES.general;
    const numSubQs = { quick: 3, medium: 5, deep: 8 }[depth] ?? 5;

    const planPrompt = `I need to research the following topic thoroughly:

"${query}"

Break this into exactly ${numSubQs} specific sub-questions that together would provide a comprehensive answer. ${domain.subQHint}

Return ONLY a JSON array of strings, each being one sub-question. No explanation, no markdown, just the JSON array.`;

    const result = await queryPerplexity(planPrompt, apiKey, {
      model: "sonar",
      focus: domain.focus,
    });

    let subQuestions: string[] = [];
    try {
      const parsed = JSON.parse(result.answer);
      if (Array.isArray(parsed)) {
        subQuestions = parsed.filter((q): q is string => typeof q === "string");
      }
    } catch {
      const matches = result.answer.match(/\[[\s\S]*?\]/g);
      if (matches) {
        for (const match of matches) {
          try {
            const parsed = JSON.parse(match);
            if (Array.isArray(parsed) && parsed.length >= 2) {
              subQuestions = parsed.filter((q): q is string => typeof q === "string");
              break;
            }
          } catch {
            continue;
          }
        }
      }
    }

    const planText = subQuestions.length > 0
      ? `## Research Plan: ${query}\n\n**Mode**: ${mode} | **Depth**: ${depth} | **Sub-questions**: ${subQuestions.length}\n\n` +
        subQuestions.map((q, i) => `${i + 1}. ${q}`).join("\n") +
        "\n\n*Run deep_research with the same parameters to execute this plan.*"
      : `Could not generate a research plan for: "${query}". Try rephrasing the query.`;

    return {
      content: [{ type: "text" as const, text: planText }],
    };
  },
);

// ── Start Server ────────────────────────────────────────────────────────────

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
