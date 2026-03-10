# Systemd Service

Create a persistent service for the gateway.

## Unit File

`/etc/systemd/system/openclaw.service`

```ini
[Unit]
Description=OpenClaw Gateway
After=network.target

[Service]
User=root
WorkingDirectory=./
EnvironmentFile=./.env
ExecStart=./.venv/bin/python ./gateway.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Commands

```bash
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
sudo systemctl status openclaw
```
