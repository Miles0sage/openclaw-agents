# Environment Variables

## Required

| Variable | Purpose |
|---|---|
| `GATEWAY_AUTH_TOKEN` | auth token for protected routes |

## Model Credentials (at least one)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude provider |
| `OPENAI_API_KEY` | OpenAI provider |
| `DEEPSEEK_API_KEY` | DeepSeek/Kimi provider |

## Optional Runtime

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | gateway port | `18789` |
| `OPENCLAW_DATA_DIR` | data path | `./data` |
| `OPENCLAW_LOG_LEVEL` | logging level | `INFO` |

## Example `.env`

```bash
GATEWAY_AUTH_TOKEN=change-me
ANTHROPIC_API_KEY=sk-ant-...
OPENCLAW_DATA_DIR=./data
PORT=18789
```
