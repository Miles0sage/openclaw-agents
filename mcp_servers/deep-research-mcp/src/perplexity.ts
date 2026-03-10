/**
 * Perplexity Sonar API client — handles all API communication.
 */

export interface PerplexityResponse {
  answer: string;
  citations: string[];
  model: string;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
}

export interface PerplexityOptions {
  model?: "sonar" | "sonar-pro";
  focus?: "web" | "academic" | "news";
  maxTokens?: number;
  systemPrompt?: string;
}

const DEFAULT_OPTIONS: Required<PerplexityOptions> = {
  model: "sonar-pro",
  focus: "web",
  maxTokens: 4096,
  systemPrompt: "You are a thorough research analyst. Synthesize findings with citations. Be balanced and factual.",
};

export async function queryPerplexity(
  query: string,
  apiKey: string,
  options: PerplexityOptions = {},
): Promise<PerplexityResponse> {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  const response = await fetch("https://api.perplexity.ai/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: opts.model,
      messages: [
        { role: "system", content: opts.systemPrompt },
        { role: "user", content: query },
      ],
      max_tokens: opts.maxTokens,
      search_focus: opts.focus,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Perplexity API ${response.status}: ${text}`);
  }

  const data = await response.json() as {
    choices: Array<{ message: { content: string } }>;
    citations?: string[];
    model: string;
    usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  };

  return {
    answer: data.choices?.[0]?.message?.content ?? "",
    citations: data.citations ?? [],
    model: data.model,
    usage: data.usage,
  };
}
