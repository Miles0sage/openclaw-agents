# RepurposeOS — MVP Build Plan

## Positioning
**One sentence:** "Drop in one piece of content, get it repurposed into every platform in 60 seconds."

## Core Agent Setup

RepurposeOS should not feel like "one big prompt."
It should run as a small social-media agent system:

1. **Strategist Agent**
   - Reads the source content
   - Pulls out hooks, key ideas, audience angle, CTA
   - Decides what is worth turning into posts

2. **Short-Form Agent**
   - Creates short-form hooks/scripts
   - Optimizes for Reels / Shorts / TikTok style outputs
   - Prioritizes punchy openings and high-retention phrasing

3. **Platform Copy Agent**
   - Rewrites for X, LinkedIn, Instagram, Reddit, email, blog summary
   - Adapts tone to the platform instead of reusing one generic format

**V2:** split Platform Copy Agent into separate platform specialists.

## Landing Page
**Headline:** One input. Every platform.
**Subheadline:** Drop a blog post, video, or podcast — RepurposeOS turns it into tweets, LinkedIn posts, email newsletters, YouTube shorts scripts, and Instagram carousels. Autonomously.

---

## 1-Week MVP Build Plan

### Day 1 (Tue) — Input Pipeline
- [ ] Create `/root/repurposeos/` repo
- [ ] Build input endpoint: `POST /repurpose` accepts URL, raw text, or file upload
- [ ] Content extractor: YouTube transcript (yt-dlp), blog post (web scrape), PDF, plain text
- [ ] Store raw content in Supabase `inputs` table
- [ ] Wire to OpenClaw gateway as a job

### Day 2 (Wed) — Output Formats
- [ ] Define 7 output formats:
  1. Twitter/X thread (5-8 tweets)
  2. LinkedIn post (professional tone)
  3. Email newsletter (subject + body)
  4. Instagram carousel (slide-by-slide text)
  5. YouTube Shorts script (< 60 sec)
  6. Reddit post (subreddit-appropriate)
  7. Blog summary (SEO-optimized)
- [ ] Create prompt templates for each format in `templates/`
- [ ] Social-media agent pipeline generates all 7 from single input
- [ ] Strategist Agent produces a shared brief before generation
- [ ] Short-Form Agent handles short-form/video-native outputs
- [ ] Platform Copy Agent handles platform-native text outputs
- [ ] Store outputs in Supabase `outputs` table
- [ ] Save each generated output as a persistent draft tied to the input + user
- [ ] Add draft status: `generated` / `edited` / `approved` / `published`

### Day 3 (Thu) — Web UI
- [ ] Single-page React app (or plain HTML + JS)
- [ ] Input form: paste URL / text / upload file
- [ ] "Repurpose" button → hits API
- [ ] Results page: tabbed view showing all 7 outputs
- [ ] Copy-to-clipboard on each output
- [ ] Save edits in-place so user can come back later
- [ ] Add "My Drafts" / history view for previous repurpose jobs
- [ ] Dark theme matching OpenClaw landing page

### Day 4 (Fri) — Polish & Edge Cases
- [ ] Add tone selector: Professional / Casual / Spicy / Educational
- [ ] Add audience selector: Developers / Business / General
- [ ] Handle long content (chunk + summarize first)
- [ ] Version history per output so edits are not lost
- [ ] Error states and loading animations
- [ ] Rate limiting (free tier: 5/day)

### Day 5 (Sat) — Demo Mode
- [ ] Pre-loaded demo examples (no API key needed):
  - Blog post → all 7 formats
  - YouTube video → all 7 formats
  - Podcast transcript → all 7 formats
- [ ] Terminal-style animation showing agent work
- [ ] Side-by-side before/after view
- [ ] Cost display per repurpose job

### Day 6 (Sun) — Deploy & Landing
- [ ] Deploy on VPS (same as OpenClaw)
- [ ] Landing page at repurposeos.com (or subdomain)
- [ ] GitHub Pages fallback
- [ ] Open Graph images for social sharing
- [ ] Record 60-second demo video

### Day 7 (Mon — OFF day, just review)
- [ ] Test all 7 formats with 5 different inputs
- [ ] Fix any broken outputs
- [ ] Final polish

---

## 5 Hackathon Demo Scenarios (each < 60 seconds)

### Demo 1: "Blog to Everything"
Drop a TechCrunch article URL → show all 7 outputs generated in real-time. Cost: $0.003.

### Demo 2: "YouTube to Twitter Thread"
Paste a 10-min YouTube video URL → auto-extract transcript → generate a viral Twitter thread with hooks, takeaways, CTA. Under 30 seconds.

### Demo 3: "Podcast to Newsletter"
Upload a podcast transcript → get a polished email newsletter with subject line, key quotes, and CTA. Show the tone toggle (casual → professional).

### Demo 4: "One Tweet to Full Content Suite"
Type a single tweet-length idea → RepurposeOS expands it into blog post, LinkedIn article, email, and 5-tweet thread. Show how it scales UP, not just reformats.

### Demo 5: "Live Cost Comparison"
Show the cost dashboard: "We just generated 35 pieces of content for $0.02. Here's what that would cost on Jasper/Copy.ai: $49/month."

---

## Pricing Tiers

| | Free | Pro ($19/mo) | Team ($49/mo) |
|---|---|---|---|
| Repurposes/month | 10 | 200 | Unlimited |
| Output formats | 3 (Twitter, LinkedIn, Email) | All 7 | All 7 + custom |
| Tone/audience selector | Default only | Full control | Full control |
| API access | No | Yes | Yes |
| Priority processing | No | Yes | Yes |
| Custom templates | No | No | Yes |
| Team members | 1 | 1 | 5 |

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | OpenClaw gateway (Python/FastAPI) | Already built, has agent routing |
| Frontend | Single HTML file or Next.js | Keep it simple, deploy anywhere |
| Database | Supabase (PostgreSQL) | Already integrated with OpenClaw |
| Content extraction | yt-dlp + BeautifulSoup + Trafilatura | Free, battle-tested |
| LLM | 3-agent social-media pipeline (Kimi 2.5 primary) | Cheap enough for MVP, specialized by role |
| Deploy | VPS first, hosted app later | Ship fast, upgrade after validation |
| Domain | repurposeos.com or app.repurposeos.com | Clean standalone brand |

---

## Architecture

```
User Input (URL/text/file)
    ↓
RepurposeOS API (FastAPI endpoint)
    ↓
Content Extractor (yt-dlp / scraper / PDF parser)
    ↓
OpenClaw Gateway → Strategist / Short-Form / Platform Copy agents
    ↓
7 Output Templates (parallel generation)
    ↓
Supabase (store inputs + outputs)
    ↓
Web UI (tabbed results view)
```

### Agent Flow

```
Input
  ↓
Strategist Agent
  ↓
Shared content brief
  ├──→ Short-Form Agent
  └──→ Platform Copy Agent
          ↓
Parallel outputs by platform
```

### Draft Persistence Requirement

RepurposeOS should treat every generated social asset as a saved draft by default.

That means:
- User can generate content, leave, and come back later
- Drafts remain attached to the original source input
- Edits overwrite the visible draft but keep revision history
- Outputs can move through a simple lifecycle: `generated` → `edited` → `approved` → `published`
- History page shows all previous repurpose jobs and their outputs

### Suggested Data Model

**`inputs`**
- `id`
- `user_id`
- `source_type` (`url` / `text` / `file`)
- `raw_content`
- `title`
- `created_at`

**`outputs`**
- `id`
- `input_id`
- `user_id`
- `platform` (`x`, `linkedin`, `email`, `instagram`, `youtube_shorts`, `reddit`, `blog`)
- `content`
- `status`
- `tone`
- `audience`
- `version`
- `created_at`
- `updated_at`

**`output_revisions`**
- `id`
- `output_id`
- `content`
- `edited_by`
- `created_at`

### UX Requirement

Primary user promise:
- "Generate now, polish later."

Minimum UI for MVP:
- Results tabs for newly generated outputs
- Save button or autosave on edit
- Drafts/history page
- Re-open old job and continue editing

---

## Brand Assets Needed
- [ ] Logo (simple, clean — "R" monogram or wordmark)
- [ ] Color palette (keep OpenClaw dark theme, add orange accent)
- [ ] OG image for social sharing
- [ ] 60-second demo video for landing page
