# Miles' Full Stack Map — Everything We Have

> Last updated: 2026-03-07

---

## The Big Picture

```mermaid
graph TB
    subgraph MILES["🎯 MILES (Vision + Approval)"]
        CLI[Claude Code CLI<br/>Opus 4.6 · $200/mo]
        CURSOR[Cursor Pro<br/>AI IDE · $20/mo]
        COPILOT[GitHub Copilot Pro<br/>Inline completions · $19/mo]
    end

    subgraph VPS["🖥️ VPS (<your-vps-ip>)"]
        GW[OpenClaw Gateway<br/>75+ tools · systemd]
        DASH[Dashboard<br/><your-domain>]
        RUNNER[Autonomous Runner<br/>6-phase pipeline]
    end

    subgraph WORKERS["☁️ Cloudflare Workers"]
        PA[PA Worker<br/><your-domain><br/>31 tools · DeepSeek V3]
        CEO[AI CEO Worker<br/><your-domain><br/>90+ tools · DeepSeek V3]
    end

    subgraph MODELS["🧠 AI Models (Cheapest → Most Powerful)"]
        BAILIAN[Bailian/Alibaba<br/>9+ models · $0.00003/call]
        KIMI[Kimi 2.5 / DeepSeek<br/>$0.14/1M tokens]
        MINIMAX[MiniMax M2.5<br/>$0.30/1M · 205K ctx]
        GROK[Grok grok-3-mini<br/>xAI]
        GEMINI[Gemini 2.5 Flash<br/>Free tier]
        OPUS[Claude Opus 4.6<br/>$15/$75/1M · Best reasoning]
    end

    subgraph MCP["🔧 MCP Servers (Tool Layer)"]
        OC_MCP[openclaw<br/>75+ tools]
        DR_MCP[deep-research-mcp<br/>3 tools · JUST BUILT]
        CTX[context7<br/>Library docs]
        SEQ[sequential-thinking<br/>Reasoning chains]
        SUPA_MCP[supabase<br/>DB queries]
        PW[playwright<br/>Browser automation]
        TS[tree-sitter<br/>Code parsing]
        CDT[chrome-devtools<br/>Live debugging]
        FC[firecrawl<br/>JS web scraping]
    end

    subgraph APIS["🌐 External APIs"]
        PERP[Perplexity API<br/>Research/search]
        NOTION[Notion API<br/>Databases + pages]
        GWS[Google Workspace<br/>89 skills · gws CLI]
        SLACK[Slack API<br/>Notifications]
        SMS_API[SMS API<br/>Text messages]
        ODDS[The Odds API<br/>200+ sportsbooks]
        GH[GitHub API<br/>gh CLI · repos/PRs]
        STRIPE[Stripe<br/>Payments · PENDING]
    end

    subgraph STORAGE["💾 Data Layer"]
        D1[Cloudflare D1<br/>Shared database]
        SUPA_DB[Supabase<br/>Barber CRM + Delhi Palace]
        MEM0[mem0<br/>Persistent agent memory]
        KG[Knowledge Graph<br/>Cross-session context]
    end

    subgraph PC["🖥️ Miles' PC (NOT YET CONNECTED)"]
        OLLAMA[Ollama + Qwen 2.5 7B<br/>RTX 4060 8GB VRAM<br/>FREE local inference]
    end

    subgraph PRODUCTS["📦 Live Products"]
        BARBER[Barber CRM<br/>Production]
        DELHI[Delhi Palace<br/>Production]
        PRESTRESS[PrestressCalc<br/>1597 tests · 12 tabs]
        OPENCLAW_PROD[OpenClaw<br/>v4.2 · Open source prep]
    end

    CLI --> GW
    CLI --> CURSOR
    CLI --> COPILOT
    CURSOR --> GH
    COPILOT --> GH

    GW --> RUNNER
    GW --> DASH
    RUNNER --> MODELS
    RUNNER --> MCP

    PA --> D1
    CEO --> D1
    CEO --> GW

    OC_MCP --> APIS
    DR_MCP --> PERP
    SUPA_MCP --> SUPA_DB

    OLLAMA -.->|SSH tunnel| GW

    GW --> PRODUCTS
```

---

## What Each Piece Does Best

```mermaid
graph LR
    subgraph THINKING["Deep Thinking"]
        A1[Claude Code CLI] --> A2[Architecture<br/>10+ file refactors<br/>Complex debugging]
        A3[Cursor Composer] --> A4[Multi-file features<br/>Codebase exploration<br/>Background agents]
    end

    subgraph SPEED["Speed / Volume"]
        B1[GitHub Copilot] --> B2[Inline completions<br/>Small fixes<br/>Boilerplate]
        B3[Bailian / Kimi] --> B4[$0.00003-0.14/call<br/>Simple agent tasks<br/>Content generation]
    end

    subgraph AUTOMATION["Automation"]
        C1[OpenClaw Gateway] --> C2[Job pipeline<br/>Multi-agent routing<br/>Cost tracking]
        C3[PA + CEO Workers] --> C4[Cron jobs<br/>Notifications<br/>Life management]
    end

    subgraph RESEARCH["Research"]
        D1[deep-research-mcp] --> D2[Parallel sub-queries<br/>Structured reports<br/>Citations]
        D3[Perplexity API] --> D4[Quick lookups<br/>Academic search<br/>News synthesis]
    end

    subgraph BUILD["Build & Deploy"]
        E1[Vercel] --> E2[Frontend deploys]
        E3[Cloudflare] --> E4[Workers + D1]
        E5[GitHub Actions] --> E6[CI/CD]
    end
```

---

## Cost Map (Monthly)

| Layer | Service | Cost | What You Get |
|-------|---------|------|-------------|
| **Brain** | Claude Max | $200/mo | Opus 4.6, Claude Code, 900 msgs/5hr, headless mode |
| **IDE** | Cursor Pro | $20/mo | Composer, background agents, BugBot, semantic indexing |
| **Completions** | GitHub Copilot Pro | $19/mo | Inline completions, Agent Mode, Actions integration |
| **Cheap Models** | Bailian (Alibaba) | ~$1/mo | 9+ models at $0.00003/call, bundled plan |
| **Cheap Models** | Kimi 2.5 / DeepSeek | ~$2/mo | Agent workhorses, $0.14/1M tokens |
| **Research** | Perplexity API | ~$5/mo | Sonar + Sonar Pro, per-call |
| **Scraping** | Firecrawl | Free tier | 500 pages/month |
| **Infra** | VPS | ~$10/mo | OpenClaw gateway, dashboard |
| **Infra** | Cloudflare | Free | Workers, D1, DNS |
| **Local** | Ollama (PC) | FREE | Not set up yet — infinite free inference |
| | **TOTAL** | **~$257/mo** | |

---

## 12 Agent Souls (Who Does What)

```mermaid
graph TB
    subgraph CHEAP["$0.14/1M — Kimi 2.5 / DeepSeek"]
        CG_PRO[CodeGen Pro<br/>Simple code tasks]
        REVIEW[Code Reviewer<br/>PR audits]
        TEST[Test Generator<br/>Edge case testing]
        BET[BettingBot<br/>Sports + odds]
        RESEARCH[Researcher<br/>Deep research]
        CONTENT[Content Creator<br/>Blog, docs, proposals]
        FINANCE[Financial Analyst<br/>Revenue, costs, pricing]
    end

    subgraph MEDIUM["$0.27-0.30/1M — Kimi Reasoner / MiniMax"]
        PENTEST[Pentest AI<br/>Security audits]
        CG_ELITE[CodeGen Elite<br/>Complex refactors]
        ARCH[Architecture Designer<br/>System design]
    end

    subgraph EXPENSIVE["$15/1M — Claude Opus 4.6"]
        OVERSEER[Overseer<br/>Coordinator / PM]
        SUPA[SupabaseConnector<br/>Precision data queries]
        DEBUG[Debugger<br/>Race conditions, heisenbugs]
    end

    OVERSEER -->|routes to| CHEAP
    OVERSEER -->|escalates to| MEDIUM
    OVERSEER -->|hard problems| EXPENSIVE
```

---

## Where New Products Plug In

```mermaid
graph TB
    subgraph EXISTING["What We Have"]
        GW[OpenClaw Gateway]
        MCP_LAYER[MCP Tool Layer]
        MODELS[12 AI Models]
        AGENTS[12 Agent Souls]
    end

    subgraph NEW_PRODUCTS["New Products To Build"]
        BRICK["🧱 3D Brick Builder<br/>Mecabricks clone<br/>~2 days"]
        HOME["🏠 Home Designer<br/>Home.by.me clone<br/>~3 days"]
        CAR["🚗 Vehicle Configurator<br/>3DTuning clone<br/>~2 days"]
        AUTOTEST["🧪 Auto-Test Runner<br/>MCP server<br/>~4-6 hours"]
        DASHBOARD["📊 AI Dev Dashboard<br/>Cost/success/time<br/>~1-2 days"]
    end

    subgraph NEW_APIS["APIs We'd Use"]
        REBRICK[Rebrickable API<br/>LEGO parts catalog · FREE]
        THREEJS[Three.js + R3F<br/>3D rendering · FREE]
        IKEA[Furniture APIs<br/>Product data]
        CAR_API[Vehicle 3D Models<br/>Model data APIs]
    end

    BRICK --> REBRICK
    BRICK --> THREEJS
    BRICK --> GW

    HOME --> IKEA
    HOME --> THREEJS
    HOME --> GW

    CAR --> CAR_API
    CAR --> THREEJS
    CAR --> GW

    AUTOTEST --> MCP_LAYER
    DASHBOARD --> GW

    GW --> AGENTS
    AGENTS --> MODELS
```

---

## The Full Pipeline (Ticket → Shipped Product)

```
📥 Input (Notion / GitHub / Slack / SMS)
   │
   ▼
🧠 OpenClaw Gateway (routes to right agent)
   │
   ├── 💰 Tiny task ($0) ──────→ Bailian ($0.00003/call)
   ├── 💰 Small task ($0.001) ─→ Kimi 2.5 ($0.14/1M)
   ├── 💰 Medium task ($0.01) ─→ MiniMax M2.5 ($0.30/1M)
   ├── 💰 Large task ($1-2) ───→ Claude Opus 4.6 ($15/1M)
   └── 💰 Local task (FREE) ──→ Ollama on PC (NOT YET SET UP)
   │
   ▼
🔧 MCP Tools (75+ tools execute the work)
   │
   ├── 🔍 Research ──→ deep-research-mcp → Perplexity
   ├── 🌐 Browse ───→ playwright / firecrawl / chrome-devtools
   ├── 💾 Data ─────→ supabase / D1 / knowledge graph
   ├── 📧 Comms ────→ Slack / SMS / Gmail / Notion
   ├── 🏗️ Code ─────→ file ops / git / GitHub / Vercel
   └── 🎰 Betting ──→ odds API / predictions / arb scanner
   │
   ▼
✅ Output (PR / Deploy / Report / Notification)
```

---

## NOT YET CONNECTED (Opportunities)

| What | Status | Effort | Impact |
|------|--------|--------|--------|
| **Ollama on PC** (RTX 4060) | Instructions saved, not installed | 30 min (Miles) | FREE local inference forever |
| **OpenRouter** | No API key yet | 30 min (sign up + add to .env) | 50 free req/day + cheap DeepSeek |
| **Stripe** | Pending go-live | 1-2 hours | Accept payments for products |
| **Claude Code headless** | Works, no automation scripts | 2-3 hours | Auto PR/review/test pipeline |
| **n8n** (workflow automation) | Not installed | 1 hour | Visual workflow builder, 400+ integrations |
| **npm publish deep-research-mcp** | Built, needs login | 5 min | Public MCP server on npm |

---

## Stack Strengths Summary

**What we're amazing at right now:**
- Multi-agent job pipeline with cost tracking
- 75+ MCP tools for almost anything
- 12 specialized agent souls with routing
- Research (deep-research-mcp + Perplexity)
- Cheap at scale ($0.00003/call with Bailian)
- Full life management (PA worker)

**What we're missing:**
- Frontend products (no customer-facing apps using the AI stack)
- Local model inference (PC not connected yet)
- Payment collection (Stripe pending)
- Public npm packages (deep-research-mcp ready but unpublished)
- Visual workflow builder (n8n not installed)
