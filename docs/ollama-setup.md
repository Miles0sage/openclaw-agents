# Ollama Local Inference Setup for OpenClaw

**Goal**: Connect Miles' local GPU (RTX 4060, 8GB VRAM) to the VPS so OpenClaw gets FREE inference.

**Cost savings**: ~$0.14 per 1M tokens (Kimi price) → $0 (local GPU)

---

## FOR MILES (Windows PC, RTX 4060)

### Step 1: Install Ollama

```powershell
# PowerShell (run as Administrator)
winget install Ollama.Ollama
```

Or download directly: https://ollama.ai/download/windows

### Step 2: Pull a Model (8GB VRAM fits these)

Open PowerShell and choose ONE model:

**Option A: Qwen 2.5 7B (Recommended — fastest, good quality)**
```powershell
ollama pull qwen2.5:7b
```

**Option B: DeepSeek Coder v2 6.7B (Code-focused, faster)**
```powershell
ollama pull deepseek-coder-v2:6.7b
```

**Option C: Mistral 7B (Balanced)**
```powershell
ollama pull mistral:7b
```

**Option D: Neural Chat 7B (Conversational)**
```powershell
ollama pull neural-chat:7b
```

Expected download: ~4-5 GB (fits in 8GB VRAM).

### Step 3: Start Ollama Server

```powershell
# Ollama runs on localhost:11434 by default
ollama serve
```

Keep this terminal open. Ollama is now listening.

### Step 4: Create SSH Reverse Tunnel (PowerShell)

Open a NEW PowerShell tab/window and run:

```powershell
# SSH reverse tunnel: VPS localhost:11434 → your PC's Ollama
ssh -R 11434:localhost:11434 root@<your-vps-ip>
```

**What this does**:
- `ssh -R` = remote port forwarding
- `11434:localhost:11434` = VPS port 11434 → your localhost Ollama
- Now the VPS can call `http://localhost:11434/api/generate` and reach YOUR GPU

Keep this tunnel open while OpenClaw jobs run.

### Step 5: Test Connectivity (on VPS)

Ask Miles to run this on the VPS to verify the tunnel works:

```bash
curl http://localhost:11434/api/tags
```

Should return:
```json
{"models": [{"name": "qwen2.5:7b", "size": 4567890}]}
```

---

## Tunnel Persistence (Optional)

If you want the tunnel to auto-reconnect on disconnect:

```powershell
# Install autossh first (via choco)
choco install autossh

# Then:
autossh -M 0 -R 11434:localhost:11434 root@<your-vps-ip>
```

Or use a scheduled task to restart the tunnel if it drops.

---

## VPS Side: OpenClaw Configuration

The VPS will:

1. Try Ollama first (FREE, via localhost:11434)
2. Fall back to Bailian ($0.00003) if tunnel is down
3. Then Kimi ($0.14), MiniMax ($0.30), Opus ($15)

This happens automatically — no config needed once the tunnel is active.

---

## Monitoring Ollama

```powershell
# Check running models
ollama list

# Check memory usage (Task Manager)
# Look for Ollama process — should use ~6-7 GB

# Pull another model (will run slower if both are in use)
ollama pull mistral:7b

# Remove a model if you need VRAM
ollama rm qwen2.5:7b
```

---

## Troubleshooting

### Tunnel says "Connection refused"

**Cause**: Ollama isn't running. Fix: Start `ollama serve` first.

### VPS can't reach Ollama

**Cause**: SSH tunnel not active. Fix: Keep the reverse tunnel terminal open.

### Model too slow

**Cause**: 8GB VRAM is max for 7B models. Try:
- Reduce `max_tokens` in OpenClaw
- Use a smaller model (5B instead of 7B)
- Check Task Manager — other apps using GPU memory?

### "Out of memory" error

**Cause**: Model + inference needs more VRAM. Try:
- Remove other running models (`ollama rm ...`)
- Use a 5B model instead of 7B
- Restart Ollama (`Ctrl+C` then `ollama serve`)

---

## Cost Comparison

| Scenario | Cost per 1M tokens |
|----------|-------------------|
| Ollama (local GPU) | $0 |
| Bailian (Qwen-coder) | $0.00003 |
| Kimi 2.5 | $0.14 |
| MiniMax M2.5 | $0.30 |
| Claude Opus | $15 |

**Monthly savings** (if 50% of jobs use Ollama): ~$35-70

---

## Testing the Tunnel from VPS

Once the reverse tunnel is active on Miles' PC, test from the VPS:

```bash
# From the VPS:
curl http://localhost:11434/api/tags

# Should return:
# {"models": [{"name": "qwen2.5:7b", ...}]}
```

If you see a response, the tunnel is ACTIVE and OpenClaw will use Ollama automatically.

## Restart OpenClaw Gateway

Once tunnel is active, restart the gateway so it loads the Ollama client:

```bash
sudo systemctl restart openclaw-gateway
```

Check logs:
```bash
sudo journalctl -u openclaw-gateway -f
```

Look for: `Provider ollama/qwen2.5:7b succeeded`

## How OpenClaw Uses Ollama

The fallback chain is automatic:

1. **Ollama (FREE)** — Try local GPU first via tunnel
   - If tunnel is DOWN → skip, continue to tier 2
   - If generation fails → skip, continue to tier 2

2. **Gemini 3-Flash (FREE)** — Fall back if Ollama unavailable
   - If rate-limited → skip to tier 3

3. **Kimi 2.5 ($0.14)** — Next cheapest
   - If rate-limited → skip to tier 4

4. **MiniMax M2.5 ($0.30)** — If Kimi fails
   - If rate-limited → skip to tier 5

5. **Anthropic ($15)** — Last resort

## Monitoring Ollama Usage

Check which provider is being used in the job logs:

```bash
# View recent jobs
cat data/jobs/latest.json | jq '.provider'

# Should show "ollama" when tunnel is active
```

Or restart with verbose logging:

```bash
RUST_LOG=debug systemctl restart openclaw-gateway
journalctl -u openclaw-gateway -f | grep -i ollama
```
