# PC Setup Quick Reference

## TL;DR - 5 Minute Setup

### 1. Generate SSH Key (PowerShell)
```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\openclaw -N ""
type $env:USERPROFILE\.ssh\openclaw.pub | ssh root@<your-vps-ip> "cat >> ~/.ssh/authorized_keys"
```

### 2. Install Ollama (PowerShell)
```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:7b
ollama pull deepseek-coder-v2:6.7b
```

### 3. Start Ollama (PowerShell, keep running)
```powershell
ollama serve
```

### 4. Create SSH Tunnel (PowerShell, new window, keep running)
```powershell
ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>
```

### 5. Verify on VPS
```bash
ssh -i ~/.ssh/openclaw root@<your-vps-ip>
curl http://localhost:11434/api/tags | jq
# Run verification script:
./scripts/connect-pc.sh
```

---

## Command Reference

| Task | Command |
|------|---------|
| **Generate SSH key** | `ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\openclaw -N ""` |
| **Add key to VPS** | `type $env:USERPROFILE\.ssh\openclaw.pub \| ssh root@<your-vps-ip> "cat >> ~/.ssh/authorized_keys"` |
| **Test SSH** | `ssh -i $env:USERPROFILE\.ssh\openclaw root@<your-vps-ip> "echo ok"` |
| **Start Ollama** | `ollama serve` |
| **Pull model** | `ollama pull qwen2.5:7b` |
| **List models** | `curl http://localhost:11434/api/tags` |
| **Start tunnel** | `ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>` |
| **Verify on VPS** | `./scripts/connect-pc.sh` |
| **Test inference** | `curl -X POST http://localhost:11434/api/generate -H "Content-Type: application/json" -d '{"model":"qwen2.5:7b","prompt":"hi"}'` |
| **Monitor GPU** | `nvidia-smi -l 1` |

---

## File Paths

| File | Path | Purpose |
|------|------|---------|
| Full Setup Guide | `./docs/pc-setup.md` | Detailed walkthrough with troubleshooting |
| SSH Private Key | `C:\Users\<You>\.ssh\openclaw` | Keep secret, do not share |
| SSH Public Key | `C:\Users\<You>\.ssh\openclaw.pub` | Already added to VPS |
| Verification Script | `./scripts/connect-pc.sh` | Check connection status on VPS |

---

## Ports & Addresses

| Service | Local PC | VPS | Tunnel Direction |
|---------|----------|-----|-------------------|
| Ollama API | `localhost:11434` | `localhost:11434` | PC → VPS (remote forward) |
| SSH | `22` | `22` | Your PC ↔ VPS |
| OpenClaw Gateway | — | `<your-domain>` | You → VPS (HTTPS) |

---

## Startup Checklist

- [ ] **SSH Key**: Generated and added to VPS?
- [ ] **Ollama**: Running (`ollama serve`)?
- [ ] **Models**: Downloaded (`ollama pull qwen2.5:7b`)?
- [ ] **Tunnel**: Active (`ssh -R 11434:...`)?
- [ ] **Verified**: Run `./scripts/connect-pc.sh` on VPS?
- [ ] **Cursor**: Connected to VPS via Remote-SSH?
- [ ] **Copilot**: Installed and signed in?

---

## One-Liner Tests

```powershell
# PowerShell — Test local Ollama
curl http://localhost:11434/api/tags

# After SSH tunnel up — Test remote access
# (From VPS or another terminal)
curl http://localhost:11434/api/tags

# Inference test (15 second timeout)
(curl -X POST http://localhost:11434/api/generate `
  -H "Content-Type: application/json" `
  -d '{"model":"qwen2.5:7b","prompt":"Hello world in Python:","stream":false}').Trim()
```

---

## Troubleshooting Flowchart

```
┌─ Can you SSH to VPS manually?
│  ├─ NO  → Check SSH key: ssh -i ~/.ssh/openclaw root@<your-vps-ip>
│  └─ YES → Continue
│
├─ Is Ollama running on your PC?
│  ├─ NO  → Run: ollama serve
│  └─ YES → Continue
│
├─ Is the SSH tunnel active?
│  ├─ NO  → Run: ssh -R 11434:localhost:11434 -i ~/.ssh/openclaw -N root@<your-vps-ip>
│  └─ YES → Continue
│
├─ Can you curl Ollama from PC?
│  ├─ NO  → Check Windows Firewall allows port 11434
│  └─ YES → Continue
│
└─ Run verification: ./scripts/connect-pc.sh
   ├─ All green → You're ready!
   └─ Red items → Fix those specific issues
```

---

## After Setup

### Daily Startup
1. Open PowerShell: `ollama serve`
2. Open another PowerShell: `ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>`
3. Keep both windows open while working

### Use in Cursor
- Open `./` via Remote-SSH
- Edit, use Copilot completions, Cursor AI naturally works

### Use in OpenClaw
- Set `.env` on VPS: `OLLAMA_BASE_URL=http://localhost:11434`
- Agents use your local GPU for all inference

### Monitor
- On VPS: `./scripts/connect-pc.sh` to check status
- On PC: `nvidia-smi -l 1` to watch GPU usage

---

## Support

- **Full docs**: `./docs/pc-setup.md`
- **Verification**: `./scripts/connect-pc.sh`
- **VPS**: <your-vps-ip>
- **Issues**: Check troubleshooting section in full docs
