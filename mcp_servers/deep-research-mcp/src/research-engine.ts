/**
 * Deep Research Engine — multi-step autonomous research with guardrails.
 *
 * 1. Planning: Decompose query into sub-questions via Perplexity
 * 2. Research: Query each sub-question in parallel (rate-limited)
 * 3. Synthesis: Combine findings into structured Markdown report
 */

import { queryPerplexity, type PerplexityOptions } from "./perplexity.js";

// ── Guardrails ──────────────────────────────────────────────────────────────

const MAX_SUB_QUESTIONS = 10;
const MAX_API_CALLS = 8;
const SESSION_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const MAX_PARALLEL = 3;

// ── Domain Mode Configs ─────────────────────────────────────────────────────

interface DomainConfig {
  system: string;
  focus: "web" | "academic" | "news";
  model: "sonar" | "sonar-pro";
  subQHint: string;
}

const DOMAIN_MODES: Record<string, DomainConfig> = {
  general: {
    system: "You are a thorough research analyst. Synthesize findings with citations. Be balanced and factual.",
    focus: "web",
    model: "sonar-pro",
    subQHint: "Break into logical sub-topics covering different angles.",
  },
  market: {
    system: "You are a market research analyst. Focus on market size, competitors, pricing, trends, and business models. Use specific numbers and data.",
    focus: "web",
    model: "sonar-pro",
    subQHint: "Cover: market size, key players, pricing models, recent trends, growth drivers, risks.",
  },
  technical: {
    system: "You are a technical researcher. Focus on implementation details, benchmarks, architecture, documentation quality, and community adoption.",
    focus: "web",
    model: "sonar-pro",
    subQHint: "Cover: architecture, performance benchmarks, developer experience, documentation, alternatives comparison.",
  },
  academic: {
    system: "You are an academic researcher. Prioritize peer-reviewed sources, methodology rigor, and citation accuracy. Note study limitations.",
    focus: "academic",
    model: "sonar-pro",
    subQHint: "Cover: key papers, methodology, findings, contradictions between studies, research gaps.",
  },
  news: {
    system: "You are a news analyst. Focus on recent developments, multiple perspectives, timeline of events, and implications.",
    focus: "news",
    model: "sonar",
    subQHint: "Cover: what happened, key players, timeline, different perspectives, implications.",
  },
  due_diligence: {
    system: "You are a due diligence analyst. Investigate thoroughly — look for red flags, verify claims, check financials, and assess risks.",
    focus: "web",
    model: "sonar-pro",
    subQHint: "Cover: company overview, financials, leadership, competitors, risks, red flags, customer reviews.",
  },
};

// ── Types ───────────────────────────────────────────────────────────────────

export interface ResearchResult {
  report: string;
  sources: string[];
  metadata: {
    query: string;
    mode: string;
    depth: string;
    subQuestions: number;
    sourcesFound: number;
    elapsedMs: number;
    apiCalls: number;
    estimatedCost: string;
  };
  plan: string[];
}

interface Finding {
  question: string;
  answer: string | null;
  citations: string[];
  error?: string;
  skipped?: boolean;
}

// ── Main Entry Point ────────────────────────────────────────────────────────

export async function deepResearch(
  query: string,
  apiKey: string,
  depth: "quick" | "medium" | "deep" = "medium",
  mode: string = "general",
  maxSources: number = 0,
): Promise<ResearchResult> {
  const start = Date.now();

  if (!query || query.trim().length < 5) {
    throw new Error("Query too short. Provide a detailed research question.");
  }

  const domain = DOMAIN_MODES[mode] ?? DOMAIN_MODES.general;
  const depthConfig = { quick: 3, medium: 5, deep: 8 } as const;
  const validDepth = (["quick", "medium", "deep"] as const).includes(depth) ? depth : "medium";
  const numSubQs = depthConfig[validDepth];
  const maxCalls = maxSources > 0 ? Math.min(maxSources, MAX_API_CALLS) : Math.min(numSubQs + 1, MAX_API_CALLS);

  let totalCalls = 0;

  // ── Phase 1: Planning ───────────────────────────────────────────────────

  const planResult = await generatePlan(query, numSubQs, domain, apiKey);
  totalCalls++;
  const subQuestions = planResult.slice(0, MAX_SUB_QUESTIONS);

  if (subQuestions.length === 0) {
    throw new Error("Failed to generate research plan.");
  }

  // ── Phase 2: Parallel Research ──────────────────────────────────────────

  const findings: Finding[] = [];
  let callsMade = 0;

  // Process in batches of MAX_PARALLEL to respect rate limits
  for (let i = 0; i < subQuestions.length; i += MAX_PARALLEL) {
    if (Date.now() - start > SESSION_TIMEOUT_MS - 30000) break;
    if (callsMade >= maxCalls) break;

    const batch = subQuestions.slice(i, i + MAX_PARALLEL);
    const batchResults = await Promise.allSettled(
      batch.map(async (sq) => {
        if (callsMade >= maxCalls) {
          return { question: sq, answer: null, citations: [], skipped: true };
        }
        callsMade++;
        totalCalls++;

        const result = await queryPerplexity(sq, apiKey, {
          model: domain.model,
          focus: domain.focus,
          systemPrompt: domain.system,
        });

        return {
          question: sq,
          answer: result.answer,
          citations: result.citations,
        };
      }),
    );

    for (const result of batchResults) {
      if (result.status === "fulfilled") {
        findings.push(result.value);
      } else {
        findings.push({
          question: batch[batchResults.indexOf(result)] ?? "unknown",
          answer: null,
          citations: [],
          error: result.reason?.message ?? "Unknown error",
        });
      }
    }
  }

  // ── Phase 3: Synthesis ──────────────────────────────────────────────────

  const report = await synthesizeReport(query, findings, domain, mode, apiKey);
  totalCalls++;

  // ── Collect sources ─────────────────────────────────────────────────────

  const seen = new Set<string>();
  const sources: string[] = [];
  for (const f of findings) {
    for (const c of f.citations) {
      if (!seen.has(c)) {
        seen.add(c);
        sources.push(c);
      }
    }
  }

  const elapsed = Date.now() - start;

  // Rough cost estimate: sonar ~$0.005/call, sonar-pro ~$0.015/call
  const costPerCall = domain.model === "sonar-pro" ? 0.015 : 0.005;
  const estimatedCost = (totalCalls * costPerCall).toFixed(3);

  return {
    report,
    sources,
    metadata: {
      query,
      mode: mode in DOMAIN_MODES ? mode : "general",
      depth: validDepth,
      subQuestions: subQuestions.length,
      sourcesFound: sources.length,
      elapsedMs: elapsed,
      apiCalls: totalCalls,
      estimatedCost: `$${estimatedCost}`,
    },
    plan: subQuestions,
  };
}

// ── Phase 1: Planning ─────────────────────────────────────────────────────

async function generatePlan(
  query: string,
  numSubQs: number,
  domain: DomainConfig,
  apiKey: string,
): Promise<string[]> {
  const planPrompt = `I need to research the following topic thoroughly:

"${query}"

Break this into exactly ${numSubQs} specific sub-questions that together would provide a comprehensive answer. ${domain.subQHint}

Return ONLY a JSON array of strings, each being one sub-question. No explanation, no markdown, just the JSON array.

Example: ["What is the market size for X?", "Who are the key competitors?", "What are recent trends?"]`;

  try {
    const result = await queryPerplexity(planPrompt, apiKey, {
      model: "sonar",
      focus: domain.focus,
    });

    const subQuestions = extractJsonArray(result.answer);
    if (subQuestions.length > 0) return subQuestions;
  } catch {
    // Fall through to fallback
  }

  return fallbackPlan(query, numSubQs);
}

function extractJsonArray(text: string): string[] {
  // Try direct parse
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      return parsed.filter((q): q is string => typeof q === "string" && q.trim().length > 0).map((q) => q.trim());
    }
  } catch {
    // continue
  }

  // Try to find JSON array in text
  const matches = text.match(/\[[\s\S]*?\]/g);
  if (matches) {
    for (const match of matches) {
      try {
        const parsed = JSON.parse(match);
        if (Array.isArray(parsed) && parsed.length >= 2) {
          return parsed.filter((q): q is string => typeof q === "string" && q.trim().length > 0).map((q) => q.trim());
        }
      } catch {
        continue;
      }
    }
  }

  return [];
}

function fallbackPlan(query: string, n: number): string[] {
  const angles = [
    `What is ${query}? Overview and background.`,
    `What are the key facts and data about ${query}?`,
    `What are the pros and cons of ${query}?`,
    `What are recent developments regarding ${query}?`,
    `What do experts say about ${query}?`,
    `What are the alternatives or competitors to ${query}?`,
    `What are the risks or challenges with ${query}?`,
    `What is the future outlook for ${query}?`,
  ];
  return angles.slice(0, n);
}

// ── Phase 3: Synthesis ────────────────────────────────────────────────────

async function synthesizeReport(
  query: string,
  findings: Finding[],
  domain: DomainConfig,
  mode: string,
  apiKey: string,
): Promise<string> {
  const sections: string[] = [];
  for (const f of findings) {
    if (f.answer) {
      const citationsStr = f.citations.length > 0 ? "\nSources: " + f.citations.slice(0, 5).join(", ") : "";
      sections.push(`### ${f.question}\n${f.answer}${citationsStr}`);
    }
  }

  if (sections.length === 0) {
    return `# Research: ${query}\n\nNo findings were retrieved. The research sources may be unavailable or the query too narrow.`;
  }

  // Skip synthesis for small result sets
  if (sections.length <= 2) {
    return `# ${query}\n\n${sections.join("\n\n---\n\n")}`;
  }

  const combined = sections.join("\n\n---\n\n");

  const synthesisPrompt = `You are writing a comprehensive research report. Synthesize these findings into a well-structured report.

TOPIC: ${query}
MODE: ${mode}

FINDINGS:
${combined.slice(0, 12000)}

Write a structured Markdown report with:
1. An executive summary (2-3 sentences)
2. Key findings organized by theme (not by sub-question)
3. Data points, statistics, and specific examples
4. Contradictions or areas of uncertainty
5. Conclusion with actionable takeaways

Use ## for sections and ### for subsections. Include inline citations where relevant.
Keep it thorough but concise — aim for quality over length.`;

  try {
    const result = await queryPerplexity(synthesisPrompt, apiKey, {
      model: domain.model,
      focus: domain.focus,
      systemPrompt: domain.system,
    });

    if (result.answer && result.answer.length > 100) {
      return `# ${query}\n\n${result.answer}`;
    }
  } catch {
    // Fallback to concatenated sections
  }

  return `# ${query}\n\n${combined}`;
}
