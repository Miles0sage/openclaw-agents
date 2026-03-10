# deep-research-mcp

MCP server for multi-step autonomous deep research using Perplexity Sonar. Decomposes questions into sub-queries, researches in parallel, and synthesizes structured reports with citations.

## Tools

### `deep_research`
Full autonomous research pipeline:
1. **Plan** — decomposes your query into sub-questions
2. **Research** — queries each sub-question in parallel via Perplexity Sonar
3. **Synthesize** — combines findings into a structured Markdown report

Parameters:
- `query` (string, required) — the research question
- `depth` — `quick` (3 sub-questions), `medium` (5), `deep` (8). Default: `medium`
- `mode` — `general`, `market`, `technical`, `academic`, `news`, `due_diligence`. Default: `general`
- `max_sources` — max API calls, 0 = auto. Default: `0`

### `quick_research`
Single-query research. No decomposition — asks the question directly and returns an answer with citations.

Parameters:
- `query` (string, required)
- `model` — `sonar` (fast) or `sonar-pro` (thorough). Default: `sonar`
- `focus` — `web`, `academic`, `news`. Default: `web`

### `research_plan`
Preview the sub-questions that would be investigated without executing the research. Useful for approval workflows.

Parameters:
- `query` (string, required)
- `depth` — `quick`, `medium`, `deep`. Default: `medium`
- `mode` — `general`, `market`, `technical`, `academic`, `news`, `due_diligence`. Default: `general`

## Setup

### Prerequisites
- Node.js >= 18
- [Perplexity API key](https://www.perplexity.ai/settings/api)

### Install

```bash
npm install -g deep-research-mcp
```

Or use directly with npx:

```bash
npx deep-research-mcp
```

### Configure

Set your Perplexity API key as an environment variable:

```bash
export PERPLEXITY_API_KEY=pplx-your-key-here
```

### Add to Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "deep-research": {
      "command": "npx",
      "args": ["-y", "deep-research-mcp"],
      "env": {
        "PERPLEXITY_API_KEY": "pplx-your-key-here"
      }
    }
  }
}
```

### Add to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "deep-research": {
      "command": "npx",
      "args": ["-y", "deep-research-mcp"],
      "env": {
        "PERPLEXITY_API_KEY": "pplx-your-key-here"
      }
    }
  }
}
```

## Domain Modes

| Mode | Focus | Best For |
|------|-------|----------|
| `general` | Balanced web research | Default for most queries |
| `market` | Market size, competitors, pricing, trends | Business research |
| `technical` | Architecture, benchmarks, docs, DX | Engineering decisions |
| `academic` | Peer-reviewed sources, methodology | Scientific research |
| `news` | Recent events, multiple perspectives | Current events |
| `due_diligence` | Financials, leadership, red flags | Company investigation |

## Cost

Uses Perplexity Sonar API. Approximate costs per research:
- **Quick** (~4 calls): ~$0.02-0.06
- **Medium** (~6 calls): ~$0.03-0.09
- **Deep** (~9 calls): ~$0.05-0.14

Exact costs depend on the model used (sonar vs sonar-pro).

## License

MIT
