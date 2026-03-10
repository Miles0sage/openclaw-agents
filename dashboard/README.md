# OpenClaw Dashboard

React dashboard for the OpenClaw FastAPI backend.

## Setup

```bash
cd dashboard
cp .env.example .env.local
npm install
npm run dev
```

The app defaults to `http://localhost:8000`. Override it with:

```bash
NEXT_PUBLIC_API_URL=http://localhost:18789
```

## Routes

- `/` overview metrics + recent jobs
- `/jobs` queue view with status filter
- `/jobs/[id]` phase timeline, cost chart, quality score, live log stream
- `/agents` agent performance cards

## Notes

- The dashboard reads from existing backend endpoints only.
- Missing or partial backend data is rendered as empty states instead of crashing.
