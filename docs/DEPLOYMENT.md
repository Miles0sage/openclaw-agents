# OpenClaw Deployment Guide

This guide covers deploying OpenClaw v4.0+ to a Linux/macOS server with systemd service management.

## Requirements

- **Python:** 3.11+ (tested with 3.13.5)
- **Node.js:** 22+ (for certain CLI tools and MCP servers)
- **OS:** Linux/macOS server (tested on Debian 13)
- **RAM:** 2GB minimum, 4GB recommended
- **Disk:** 10GB free space for code, logs, and cache
- **Network:** Public IP or reverse proxy (Cloudflare recommended)
- **Service Manager:** Systemd for background process management
- **Git:** For cloning and pulling updates

## Installation

### Clone and Set Up

```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Configuration

Copy the example environment file and edit with your API keys:

```bash
cp .env.example .env
nano .env
```

### Environment Variables Overview

#### Core Settings

- `PORT` — Gateway HTTP port (default: 18789)
- `NODE_ENV` — Environment (development, staging, production)
- `LOG_LEVEL` — Logging verbosity (debug, info, warn, error)
- `GATEWAY_AUTH_TOKEN` — Secret token for API authentication

#### AI Providers

- `ANTHROPIC_API_KEY` — Claude API key (required)
- `GEMINI_API_KEY` — Google Gemini API key (optional, for OpenCode executor)
- `DEEPSEEK_API_KEY` — DeepSeek API key (optional, for deep reasoning tasks)
- `PERPLEXITY_API_KEY` — Perplexity API key (optional, for web research)

#### Communication Services

- `SLACK_BOT_TOKEN` — Slack workspace token
- `SLACK_SIGNING_SECRET` — Slack request verification
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `DISCORD_BOT_TOKEN` — Discord bot token
- `TWILIO_ACCOUNT_SID` — Twilio account ID
- `TWILIO_AUTH_TOKEN` — Twilio auth token
- `TWILIO_PHONE_NUMBER` — Twilio phone number

#### Voice & Audio

- `ELEVENLABS_API_KEY` — ElevenLabs text-to-speech
- `VAPI_PUBLIC_KEY` — Vapi AI voice calling
- `VAPI_PRIVATE_KEY` — Vapi private API key

#### Database

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase anonymous key
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service role key

#### Cache & State

- `UPSTASH_REDIS_REST_URL` — Upstash Redis REST endpoint
- `UPSTASH_REDIS_REST_TOKEN` — Upstash Redis token

#### Trading (Optional)

- `KALSHI_API_KEY` — Kalshi prediction market API
- `ODDS_API_KEY` — The Odds API for sportsbook data

## Systemd Service Setup

### Create Service File

Create `/etc/systemd/system/openclaw-gateway.service`:

```ini
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=./
ExecStart=/usr/bin/python3 ./gateway.py
Restart=always
RestartSec=5
TimeoutStopSec=300
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### Deploy Service

```bash
# Copy service file
sudo cp openclaw-gateway.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable openclaw-gateway

# Start the service
sudo systemctl start openclaw-gateway

# Verify status
sudo systemctl status openclaw-gateway
```

### Service Management

```bash
# Start/stop/restart
sudo systemctl start openclaw-gateway
sudo systemctl stop openclaw-gateway
sudo systemctl restart openclaw-gateway

# View live logs
journalctl -u openclaw-gateway -f

# View last 50 lines
journalctl -u openclaw-gateway -n 50

# View logs since specific time
journalctl -u openclaw-gateway --since "2 hours ago"
```

## Cloudflare / Reverse Proxy Setup

### DNS Configuration

1. Point your domain (e.g., `<your-domain>`) to your server IP
2. In Cloudflare DNS settings, create an A record pointing to your VPS IP

### Cloudflare Proxy Settings

1. Set SSL/TLS to **Full (Strict)**
2. Enable **WebSocket support** (Speed > Optimization > WebSockets ON)
3. Set **Minimum TLS Version** to 1.2
4. Configure **Caching Rules** to bypass cache for `/api/*` endpoints

### HTTPS Support

- Cloudflare automatically provisions and renews SSL certificates
- All traffic between Cloudflare and your server should use HTTPS
- Configure your server to trust Cloudflare's origin certificate

## OpenCode Configuration

Each project directory needs a `.opencode.json` file for the Gemini-powered executor:

```json
{
  "model": "gemini-2.5-flash",
  "permissions": {
    "allow": "all"
  }
}
```

Place this file in:

- `./.opencode.json` (main project)
- `/root/Barber-CRM/.opencode.json` (per-project)
- `/root/Delhi-Palace/.opencode.json` (per-project)
- Etc. for each managed project

## Monitoring & Health Checks

### Health Endpoint

```bash
curl https://<your-domain>/api/health
```

Expected response:

```json
{
  "status": "healthy",
  "timestamp": "2026-03-04T22:45:30Z",
  "uptime_seconds": 3600
}
```

### Active Jobs

```bash
curl -H "Authorization: Bearer $GATEWAY_AUTH_TOKEN" \
  https://<your-domain>/api/monitoring/active
```

### Dashboard Access

- **Job Viewer:** `https://<your-domain>/job_viewer.html`
- **Mission Control:** `https://<your-domain>/mission_control.html`

### Log Monitoring

```bash
# Follow gateway logs in real time
journalctl -u openclaw-gateway -f

# Filter by severity
journalctl -u openclaw-gateway --priority err
```

## Troubleshooting

### Port Already in Use

```bash
# Find process using port 18789
lsof -i :18789

# Kill conflicting process
kill -9 <PID>
```

### Gateway Won't Start

```bash
# Check systemd logs
journalctl -u openclaw-gateway -n 100

# Test manually (outside systemd)
cd ./
python3 gateway.py
```

### WebSocket Connection Failed

- Ensure Cloudflare WebSocket support is enabled
- Check that your firewall allows WebSocket upgrades
- Verify `WSS://` protocol is being used (not `WS://`)

### AI Provider Rate Limits

**Gemini Rate Limits:**

- Free tier: very restrictive (2-4 requests/min)
- **Fix:** Enable billing at [aistudio.google.com](https://aistudio.google.com)
- Paid tier: 60,000 requests/min

**Anthropic Rate Limits:**

- Claude API: 1M tokens/min standard, higher with enterprise plan
- Check your account at [console.anthropic.com](https://console.anthropic.com)

### Module Import Errors

If Python can't find modules:

```bash
# Use system packages flag for pip
pip install --break-system-packages -r requirements.txt

# Or ensure venv is activated
source ./venv/bin/activate
```

### Database Connection Issues

```bash
# Test Supabase connectivity
python3 -c "from supabase import create_client; print('OK')"

# Verify environment variables
echo $SUPABASE_URL $SUPABASE_ANON_KEY
```

## Deployment Checklist

- [ ] Python 3.11+ installed
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file created and populated with all required keys
- [ ] `.opencode.json` placed in project roots
- [ ] Systemd service file copied to `/etc/systemd/system/`
- [ ] Service enabled and started (`systemctl enable/start openclaw-gateway`)
- [ ] Domain DNS configured and pointing to server
- [ ] Cloudflare reverse proxy configured with WebSocket support
- [ ] Health endpoint responds (`GET /api/health`)
- [ ] Logs being monitored (`journalctl -u openclaw-gateway -f`)
- [ ] Backup strategy in place (database, logs, code)

## Updating OpenClaw

To update to a new version:

```bash
# Stop the service
sudo systemctl stop openclaw-gateway

# Pull latest changes
cd ./
git pull origin main

# Update dependencies
pip install -r requirements.txt

# Start the service
sudo systemctl start openclaw-gateway

# Verify
journalctl -u openclaw-gateway -n 20
```

## Security Considerations

- Never commit `.env` files to version control
- Rotate `GATEWAY_AUTH_TOKEN` regularly
- Use strong, unique API keys for each provider
- Enable firewall rules to allow only necessary ports (443 for HTTPS, 22 for SSH)
- Keep systemd service running as a non-root user (`User=openclaw`)
- Regularly review gateway logs for unauthorized access attempts
- Monitor database query patterns for anomalies
- Use Cloudflare DDoS protection in production

## Support

For deployment issues or questions:

- Check logs: `journalctl -u openclaw-gateway -f`
- Review `.env` configuration
- Consult API provider documentation for rate limits
- Contact OpenClaw support with logs attached
