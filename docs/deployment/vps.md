# VPS Setup

Deploy OpenClaw gateway on Linux with Python, systemd, and reverse proxy.

## Host Requirements

- Ubuntu 22.04+ or equivalent
- Python 3.11+
- 2+ vCPU, 4+ GB RAM

## Install

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx
cd /opt
sudo git clone https://github.com/cybershield-agency/openclaw.git
cd openclaw
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source /opt/openclaw/.venv/bin/activate
cd /opt/openclaw
python gateway.py
```
