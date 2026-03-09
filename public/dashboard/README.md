# OpenClaw Dev Dashboard v2

A professional, real-time monitoring dashboard for the OpenClaw AI agent system. Built with vanilla JavaScript, Tailwind CSS, and Chart.js — no build step required.

## Features

### System Monitoring
- **Gateway Status**: Real-time health indicators (Healthy/Degraded/Unhealthy)
- **API Latency**: Millisecond-precision response time tracking
- **Uptime Tracking**: Process uptime with human-readable format
- **Resource Usage**: Memory (MB) and CPU (%) utilization graphs

### Job Pipeline
- **Live Job Queue**: Real-time view of active, pending, and completed jobs
- **Status Distribution**: Running/Pending/Done/Failed counts
- **Job Details**: Task name, status, elapsed time, cost, and agent
- **Agent Performance**: Success rates and cost per agent

### Financial Dashboard
- **Cost Breakdown**: Daily, weekly, and monthly burn rates
- **Model Distribution**: Pie chart of token usage by model
- **By-Agent Costs**: Cost attribution to each agent
- **Trending Costs**: Visual bars with percentage utilization

### Analytics
- **Tool Usage Heatmap**: 24-hour activity distribution
- **Job Status Distribution**: Visual breakdown of job outcomes
- **Recent Results**: Recent job completions with metadata

## Access

**URL**: `http://localhost:18789/dashboard/v2/`

**No authentication required** — the dashboard is exempt from gateway auth.

## Architecture

### Frontend (Single Page App)
- **Framework**: Vanilla JavaScript (no build tools)
- **Styling**: Tailwind CSS (CDN)
- **Charts**: Chart.js (doughnut charts)
- **Luxon**: DateTime formatting (not currently used, can be removed)

### API Endpoints (Backend)

All endpoints are **unauthenticated** for dashboard access:

| Endpoint | Response | Refresh Rate |
|----------|----------|--------------|
| `/api/health` | System health, uptime, memory, CPU | Per-request |
| `/api/monitoring/active` | Active jobs with status | Per-request |
| `/api/monitoring/costs` | Cost metrics by model/agent | Per-request |
| `/api/monitoring/phases` | Job execution phases | Per-request |

### Styling & Design

**Theme**: Dark mode with glassmorphism
- Background: Gradient (slate-900 to slate-700)
- Cards: Translucent glass effect (rgba with backdrop blur)
- Colors: Indigo primary, Green/Amber/Red status indicators
- Animations: Smooth fade-ins, pulse indicators, chart updates

**Responsive**: Mobile-friendly grid layout
- 1 column on mobile
- 2-3 columns on tablet
- Full layout on desktop

## File Structure

```
/root/openclaw/public/dashboard/
├── index.html          # Complete single-page app
└── README.md           # This file
```

The HTML file includes:
- Inline CSS (550+ lines)
- Inline JavaScript with async data fetching
- No external dependencies except CDN links
- All functionality in one file (easy to deploy)

## Configuration

### Auto-Refresh Rate
```javascript
// Fetches every 30 seconds
setInterval(fetchDashboardData, 30000);
```

Change the interval by modifying the millisecond value.

### API URL Detection
```javascript
const getApiUrl = (endpoint) => {
    const proto = window.location.protocol;
    const host = window.location.hostname;
    const port = window.location.port ? `:${window.location.port}` : '';
    return `${proto}//${host}${port}${endpoint}`;
};
```

Automatically detects protocol, host, and port from browser.

## Data Visualization

### Model Distribution (Doughnut Chart)
- Dynamic colors per model
- Updates on each refresh
- Responsive sizing

### Cost Bars
- Animated width transitions
- Percentage-based scaling
- Value labels in USD

### Tool Heatmap
- 24-hour grid (0-23)
- Color intensity reflects usage
- Hover tooltips

## Future Enhancements

1. **WebSocket SSE**: Real-time updates instead of polling
2. **Advanced Filtering**: Filter by agent, project, status
3. **Time Range Selection**: Custom date ranges for costs
4. **Export**: CSV/JSON export of metrics
5. **Alerts**: Toast notifications for critical events
6. **Dark/Light Theme Toggle**: User preference storage

## Deployment

### On Gateway
The dashboard is already mounted at `/dashboard/v2/` and served as static files.

### Standalone
To use standalone:
```bash
# Start a simple HTTP server
cd /root/openclaw/public/dashboard/
python3 -m http.server 8000
# Visit http://localhost:8000/
```

## Testing

Run the test suite:
```bash
/tmp/dashboard_test.sh
```

Verify endpoints:
```bash
curl http://localhost:18789/api/health
curl http://localhost:18789/api/monitoring/active
curl http://localhost:18789/api/monitoring/costs
```

## Browser Compatibility

- Chrome/Chromium 90+
- Firefox 88+
- Safari 14+
- Edge 90+

Requires:
- ES6 JavaScript support
- Fetch API
- CSS Grid & Flexbox

## Performance

- **Initial Load**: ~100KB (HTML + CSS + JS)
- **API Calls**: 3 parallel requests per refresh
- **Memory**: ~50MB in browser
- **Update Latency**: <500ms per refresh

## Security

- **No Secrets**: Dashboard reads only public metrics
- **No Auth Headers**: Uses public endpoints
- **CORS**: Already enabled on gateway
- **XSS Safe**: Data sanitized in DOM updates

## Troubleshooting

### Dashboard shows "No active jobs"
- This is normal if the system is idle
- Check `/api/monitoring/active` manually:
  ```bash
  curl http://localhost:18789/api/monitoring/active | jq .
  ```

### Costs show $0.00
- Costs only accumulate when jobs run
- Check `/api/monitoring/costs` manually:
  ```bash
  curl http://localhost:18789/api/monitoring/costs | jq .
  ```

### Charts not rendering
- Check browser console for errors (F12)
- Ensure Chart.js CDN is accessible
- Verify JavaScript is enabled

### API endpoints 401 Unauthorized
- The `/api/live/*` endpoints require auth, dashboard uses `/api/monitoring/*` instead
- If you see 401s on `/api/monitoring/`, add them to exempt paths in gateway.py

## Credits

Built for OpenClaw v4.2 as a portfolio piece.
- Design: Modern glassmorphism aesthetic
- Performance: Zero-build, vanilla JavaScript
- UX: Real-time updates, responsive layout, intuitive cards
