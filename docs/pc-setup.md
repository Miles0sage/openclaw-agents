# Connect Your Windows PC to OpenClaw VPS

## Overview

This guide connects your local Windows 11 PC to the OpenClaw VPS, enabling:
- **Ollama local inference** (7B/6.7B models run on your RTX 4060, accessed from VPS)
- **Cursor Pro remote SSH editing** (edit VPS code with full AI assistance)
- **GitHub Copilot** (completions work seamlessly on remote VPS files)
- **GPU acceleration** for ML tasks without paying for cloud GPU

## System Requirements

- **Local PC**: Windows 11, 32GB RAM, RTX 4060 (8GB VRAM), CUDA 13.1
- **VPS**: <your-vps-ip> (already running OpenClaw)
- **Network**: Stable internet connection (SSH tunnels are persistent)
- **Tools**: PowerShell 7+ or WSL2 bash

## Step 1: SSH Key Setup (One-Time)

### Generate SSH Key

Open **PowerShell** and generate an Ed25519 key:

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\openclaw -N ""
```

This creates:
- `C:\Users\<YourUser>\.ssh\openclaw` (private key — keep secret)
- `C:\Users\<YourUser>\.ssh\openclaw.pub` (public key — send to VPS)

### Add Public Key to VPS

Copy your public key to the VPS:

```powershell
type $env:USERPROFILE\.ssh\openclaw.pub | ssh root@<your-vps-ip> "cat >> ~/.ssh/authorized_keys"
```

You'll be prompted for the VPS root password (one time only).

### Verify Connection

```powershell
ssh -i $env:USERPROFILE\.ssh\openclaw root@<your-vps-ip> "echo 'SSH works!'"
```

If successful, you'll see `SSH works!` without a password prompt.

## Step 2: Install Ollama Locally

### Download and Install

Use `winget` (Windows Package Manager):

```powershell
winget install Ollama.Ollama
```

Or download from [ollama.ai](https://ollama.ai) and run the installer.

### Verify Installation

```powershell
ollama --version
ollama serve  # Should start on localhost:11434
```

Keep this terminal open or let Ollama run as a service.

### Pull Models

Open a new PowerShell window and pull the models you need:

```powershell
ollama pull qwen2.5:7b
ollama pull deepseek-coder-v2:6.7b
ollama pull nomic-embed-text
```

Each model download takes 2-5 minutes depending on internet speed.

### Verify Models

```powershell
curl -Method GET http://localhost:11434/api/tags | ConvertFrom-Json | ForEach-Object {$_.models}
```

You should see your downloaded models listed.

## Step 3: Create SSH Tunnel

This tunnel makes your local Ollama available to the VPS at `localhost:11434`.

### Option A: Manual SSH Tunnel (PowerShell)

Run this whenever you want to connect your PC to the VPS:

```powershell
ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>
```

This command:
- `-R 11434:localhost:11434` — forwards VPS port 11434 to your local port 11434
- `-N` — no remote command (tunnel only, no shell)
- Runs until you press `Ctrl+C`

Keep this terminal open while working.

### Option B: Persistent Tunnel (WSL2 / Git Bash)

For a tunnel that survives disconnects, use `autossh` (requires WSL2 or Git Bash):

```bash
# Install autossh (WSL2):
sudo apt update && sudo apt install -y autossh

# Create tunnel (runs in background):
autossh -M 0 -f -N -R 11434:localhost:11434 \
  -i ~/.ssh/openclaw \
  root@<your-vps-ip>
```

This tunnel auto-reconnects if the connection drops.

### Option C: Create a Scheduled Task (Advanced)

To run the tunnel automatically when Windows starts:

1. Save this script as `C:\Scripts\start-tunnel.ps1`:

```powershell
# Start OpenClaw tunnel
$key = "$env:USERPROFILE\.ssh\openclaw"
$cmd = "ssh -R 11434:localhost:11434 -i $key -N root@<your-vps-ip>"
Invoke-Expression $cmd
```

2. Open Task Scheduler and create a task to run this script at startup.

## Step 4: Test Ollama Connection from VPS

SSH into the VPS and verify the tunnel is active:

```bash
ssh -i ~/.ssh/openclaw root@<your-vps-ip>
# Then on VPS:
curl -s http://localhost:11434/api/tags | jq '.models[].name'
```

You should see your model names (e.g., `qwen2.5:7b`, `deepseek-coder-v2:6.7b`).

If empty, check:
1. Is Ollama running on your PC? (`ollama serve`)
2. Is the SSH tunnel active? (PowerShell window showing `ssh -R ...` should be running)
3. Do you have firewall rules blocking port 11434? (Windows Defender Firewall)

## Step 5: Configure Cursor for Remote SSH

### Install Cursor

Download from [cursor.sh](https://cursor.sh) and install.

### Connect to VPS

1. Open **Cursor**
2. Press `Cmd+Shift+P` (or `Ctrl+Shift+P` on Windows) to open Command Palette
3. Type: `Remote-SSH: Connect to Host`
4. Enter: `root@<your-vps-ip>`
5. Select: `Linux` (when prompted for OS)
6. Wait for connection (first time is slow as it installs remote server)

### Open OpenClaw Folder

1. Press `Cmd+K Cmd+O` (or `Ctrl+K Ctrl+O`)
2. Type path: `./`
3. Press Enter

Cursor now edits files on the VPS with full AI assistance.

### Verify Cursor Works

1. Open `./gateway.py`
2. Click on a function and press `Cmd+I` (inline chat)
3. Ask Cursor a question about the code — it should use the VPS's full context

## Step 6: Enable GitHub Copilot

### Install Extension

1. In Cursor, press `Cmd+Shift+X` (Extensions)
2. Search: `GitHub Copilot`
3. Click Install

### Sign In

1. Press `Cmd+Shift+P` → `GitHub Copilot: Sign In`
2. Browser opens, authorize with your GitHub account
3. Return to Cursor — you're signed in

### Use Copilot

Start typing in any file on the remote VPS and Copilot suggests completions. Works seamlessly over SSH.

## Step 7: Configure OpenClaw to Use Your Ollama

The VPS needs to know where to find your Ollama instance. Edit the OpenClaw config:

```bash
ssh -i ~/.ssh/openclaw root@<your-vps-ip>
cd ./
```

Edit `.env` or `config.py` to add:

```bash
# Use local PC Ollama via tunnel
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=qwen2.5:7b
OLLAMA_CODER_MODEL=deepseek-coder-v2:6.7b
```

Restart the gateway:

```bash
systemctl restart openclaw-gateway
journalctl -u openclaw-gateway -f  # Watch logs
```

## Step 8: Verify Everything Works

### From PowerShell (Your PC)

```powershell
# Ollama is running locally
curl http://localhost:11434/api/tags

# SSH tunnel is active (keep this window open)
ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>
```

### From VPS Terminal

```bash
ssh -i ~/.ssh/openclaw root@<your-vps-ip>

# Check Ollama tunnel
curl -s http://localhost:11434/api/tags | jq

# Run a test query on your local model
curl -s http://localhost:11434/api/generate -d '{"model": "qwen2.5:7b", "prompt": "Hello"}' -X POST | jq
```

### From Cursor

1. Open `./gateway.py`
2. Use inline chat: "What does the `authorize_request` function do?"
3. Cursor should provide answer with context awareness

## Troubleshooting

### "ssh: connect to host <your-vps-ip> port 22: Connection timed out"

- Check your internet connection
- Check if VPS is reachable: `ping <your-vps-ip>` (from PowerShell)
- Check Windows Firewall: Allow SSH through Windows Defender Firewall

### "Ollama: NOT CONNECTED" on VPS

- Is Ollama running locally? Open PowerShell and run `ollama serve`
- Is the SSH tunnel active? (Check the PowerShell window with `ssh -R ...`)
- Firewall blocking port 11434? Open Windows Defender Firewall → Allow app through → check if Ollama is listed

### Cursor SSH Connection Fails

- Verify SSH works manually first: `ssh -i ~/.ssh/openclaw root@<your-vps-ip>`
- In Cursor, check remote server logs: Press `Cmd+Shift+P` → `Remote-SSH: Show Remote Server Log`
- Ensure `./` exists on VPS (it should)

### "Permission denied (publickey)"

- Verify public key was added: `ssh-keygen -y -f ~/.ssh/openclaw` should show the public key
- SSH into VPS manually (with password) and check: `cat ~/.ssh/authorized_keys`
- If key is not there, add it again (Step 1)

### Copilot Completions Not Working

- Ensure GitHub Copilot is installed and you're signed in
- Check if Copilot is enabled for the workspace: `Cmd+Shift+P` → `Copilot: Enable`
- Copilot sometimes disables on remote connections — toggle it off and back on

## Network & Security Notes

### Why SSH Tunnels Are Safe

- SSH encryption protects data between your PC and VPS
- You authenticate with your SSH key (Ed25519), not a password
- The tunnel is one-way: VPS can access your Ollama, but your PC can't access VPS resources directly

### Keeping the Tunnel Alive

- If you're using Option A (manual SSH tunnel), the connection drops if your PC sleeps
- Use Option B (autossh) for persistent connections through network interruptions
- Ensure your Wi-Fi doesn't disconnect (disable sleep while connected)

### Bandwidth Considerations

- Ollama model inference over SSH tunnel uses ~1-2 Mbps per inference
- Keep the SSH connection local (same network or stable internet)

## Monitoring Your GPU

### Check GPU Usage on PC

Open PowerShell and monitor GPU:

```powershell
# Using NVIDIA GPU monitor (if installed):
nvidia-smi -l 1  # Refreshes every 1 second
```

During Ollama inference, you should see GPU utilization spike to 80-95%.

### Check Model Performance

Test inference speed on your PC:

```powershell
# Time a generation
Measure-Object -InputObject (
  curl -s -X POST http://localhost:11434/api/generate `
    -H "Content-Type: application/json" `
    -d '{"model": "qwen2.5:7b", "prompt": "Write a hello world in Python"}'
) -TotalMilliseconds
```

For qwen2.5:7b on RTX 4060, expect 20-40 tokens/second.

## Next Steps

1. **SSH Tunnel Active?** Start the tunnel: `ssh -R 11434:localhost:11434 -i $env:USERPROFILE\.ssh\openclaw -N root@<your-vps-ip>`
2. **Cursor Remote?** Connect via `Cmd+Shift+P` → `Remote-SSH: Connect to Host`
3. **Using Models on VPS?** Update `.env` to use your Ollama instance
4. **Want Persistent Tunnel?** Set up autossh or scheduled task

## Reference

- **VPS Address**: <your-vps-ip>
- **Ollama Docs**: https://ollama.ai
- **Cursor SSH Docs**: https://cursor.sh/docs/remote-ssh
- **GitHub Copilot**: https://github.com/features/copilot
