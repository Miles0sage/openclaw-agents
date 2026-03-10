"""
Telegram webhook router for OpenClaw gateway.

Provides two Telegram bots:
1. Main Telegram bot — Routes to Claude Code agents
2. CoderClaw bot — Dedicated Claude Code controller with persistent sessions

Features:
- Webhook deduplication (persistent, survives restarts)
- Session management for conversation continuity
- Direct Claude Code execution with --resume
- Tmux agent spawning for long-running tasks
- Job queue routing for complex tasks
"""

import os
import json
import asyncio
import uuid
import time
import base64
import pathlib
import logging
import re as _re_tg
from datetime import datetime, timezone
from typing import Optional
from html import escape as html_escape

import httpx
from fastapi import APIRouter, Request

# ── Shared dependencies ──────────────────────────────────────────────────────
from .shared import (
    CONFIG, session_store, save_session_history, broadcast_event,
    get_agent_config, call_model_with_escalation, call_model_for_agent,
    build_channel_system_prompt, trim_history_if_needed,
    anthropic_client, agent_router, metrics, BASE_DIR, logger
)

# ── Other module imports ─────────────────────────────────────────────────────
from job_manager import create_job, list_jobs
from tmux_spawner import get_spawner

# ── Router setup ─────────────────────────────────────────────────────────────
router = APIRouter(prefix="/telegram", tags=["telegram"])

# ── Constants ────────────────────────────────────────────────────────────────
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_USER_ID", "8475962905")
CODERCLAW_BOT_TOKEN = os.getenv("CODERCLAW_BOT_TOKEN", "")
CODERCLAW_SESSIONS_DIR = pathlib.Path("./data/coderclaw_sessions")
CODERCLAW_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ── Persistent dedup for Telegram webhooks (survives gateway restarts) ──
_TG_DEDUP_FILE = pathlib.Path("./data/tg_dedup.json")
_TG_DEDUP_TTL = 600  # 10 minutes

# Task patterns
TASKS_FILE = pathlib.Path(BASE_DIR) / "data" / "tasks.json"

# Claude Code patterns
_CLAUDE_CODE_PATTERNS = [
    # "build X", "fix X", "create X", "deploy X", "refactor X"
    (r'^\s*(?:build|fix|create|deploy|refactor|implement|add|update|upgrade|wire|connect|ship)\s+(.+)', 'single'),
    # "run all in parallel", "run these in parallel: X, Y, Z"
    (r'^\s*run\s+(?:all|these|everything)\s+in\s+parallel(?:[:\s]+(.+))?', 'parallel'),
    # "run: X" or "agent: X" — direct agent command
    (r'^\s*(?:run|agent|execute|do)[:\s]+(.+)', 'single'),
    # "PR for X", "create PR", "make a PR"
    (r'^\s*(?:create|make|open|submit)\s+(?:a\s+)?(?:pr|pull request)(?:\s+(?:for\s+)?(.+))?', 'pr'),
    # "spawn agent: X"
    (r'^\s*spawn\s+(?:agent[:\s]+)?(.+)', 'single'),
]

# Call patterns — trigger outbound sales calls
_CALL_PATTERNS = [
    r'^\s*call\s+(?:the\s+)?leads?(?:\s+for\s+(.+))?',  # "call leads", "call the leads for restaurants"
    r'^\s*call\s+(.+)',  # "call Mountain Grill", "call 928-555-1234"
]

# Lead finder patterns — handled separately from agents
_LEAD_FINDER_PATTERNS = [
    r'^\s*find\s+(?:leads?\s+(?:for\s+)?)?(\w[\w\s]+?)(?:\s+in\s+(.+))?$',
    r'^\s*search\s+(?:for\s+)?(\w[\w\s]+?)(?:\s+in\s+(.+))?$',
    r'^\s*(?:get|show|list)\s+(?:me\s+)?(\w[\w\s]+?)(?:\s+(?:in|near|around)\s+(.+))?$',
]

_TASK_PATTERNS = [
    r'^create task[:\s]+(.+)', r'^todo[:\s]+(.+)', r'^add task[:\s]+(.+)',
    r'^remind me to[:\s]+(.+)', r'^new task[:\s]+(.+)',
]

# Brick Builder patterns — trigger brick builder AI endpoints
_BRICK_BUILDER_PATTERNS = [
    (r'^\s*(?:brick|bricks)\s+suggest\s+(.+)', 'suggest'),  # "brick suggest build a tower"
    (r'^\s*(?:brick|bricks)\s+describe\s+(.+)', 'describe'),  # "brick describe my build"
    (r'^\s*(?:brick|bricks)\s+complete\s+(.+)', 'complete'),  # "brick complete my block"
    (r'^\s*/bricks?\s*$', 'list'),  # "/brick" or "/bricks" — list saved builds
    (r'^\s*show\s+(?:brick|bricks)\s*$', 'list'),  # "show bricks"
]


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — Telegram send, token resolution, dedup
# ═══════════════════════════════════════════════════════════════════════════

def _get_telegram_token() -> str:
    """Resolve Telegram bot token from config or env."""
    token = CONFIG.get("channels", {}).get("telegram", {}).get("botToken", "")
    if token.startswith("${") and token.endswith("}"):
        token = os.getenv(token[2:-1], "")
    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return token


async def _tg_send(chat_id, text: str, reply_to: int = None):
    """Send a message to Telegram. Splits long messages. HTML parse mode with plain-text fallback."""
    token = _get_telegram_token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Split into 4096-char chunks (Telegram limit)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for i, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if reply_to and i == 0:
                payload["reply_to_message_id"] = reply_to
                payload["allow_sending_without_reply"] = True
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    # Retry without HTML parse mode and without reply
                    payload.pop("parse_mode", None)
                    payload.pop("reply_to_message_id", None)
                    await client.post(url, json=payload)
            except Exception as e:
                logger.error(f"Telegram send error: {e}")


async def _tg_typing(chat_id):
    """Send typing indicator."""
    token = _get_telegram_token()
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
    except Exception:
        pass


async def _tg_download_photo(file_id: str) -> tuple[str, str]:
    """Download a Telegram photo by file_id. Returns (base64_data, media_type)."""
    token = _get_telegram_token()
    if not token:
        raise ValueError("No Telegram bot token configured")
    async with httpx.AsyncClient(timeout=30) as client:
        # Get file path from Telegram
        resp = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]
        # Download the file
        dl_resp = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        dl_resp.raise_for_status()
        b64 = base64.standard_b64encode(dl_resp.content).decode("utf-8")
        # Determine media type from extension
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
        media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
        media_type = media_types.get(ext, "image/jpeg")
        return b64, media_type


async def _tg_analyze_photo(chat_id: int, photo_b64: str, media_type: str, caption: str, msg_id: int):
    """Send a photo to Gemini Flash for vision analysis. Cheap: $0.10/1M input tokens."""
    try:
        prompt = caption.strip() if caption else "What ingredients can you see in this photo? List them clearly with estimated quantities if possible."
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            await _tg_send(chat_id, "No GEMINI_API_KEY configured for photo analysis", reply_to=msg_id)
            return

        payload = {
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": media_type, "data": photo_b64}},
                {"text": prompt},
            ]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            await _tg_send(chat_id, "No response from vision model", reply_to=msg_id)
            return
        parts = candidates[0].get("content", {}).get("parts", [])
        result = "\n".join(p["text"] for p in parts if "text" in p)
        usage = data.get("usageMetadata", {})
        tokens = usage.get("promptTokenCount", 0) + usage.get("candidatesTokenCount", 0)
        logger.info(f"Photo analysis via Gemini Flash: {tokens} tokens")
        await _tg_send(chat_id, result, reply_to=msg_id)
    except Exception as e:
        logger.error(f"Photo analysis error: {e}")
        await _tg_send(chat_id, f"Failed to analyze photo: {e}", reply_to=msg_id)


def _tg_dedup_check(update_id: int, bot: str = "cc") -> bool:
    """Return True if this update_id was already seen (duplicate). Thread-safe via file."""
    now = time.time()
    key = f"{bot}:{update_id}"
    try:
        if _TG_DEDUP_FILE.exists():
            seen = json.loads(_TG_DEDUP_FILE.read_text())
        else:
            seen = {}
    except (json.JSONDecodeError, OSError):
        seen = {}
    # Prune expired entries
    seen = {k: v for k, v in seen.items() if now - v < _TG_DEDUP_TTL}
    if key in seen:
        return True  # Duplicate
    seen[key] = now
    try:
        _TG_DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TG_DEDUP_FILE.write_text(json.dumps(seen))
    except OSError:
        pass
    return False  # New update


# ═══════════════════════════════════════════════════════════════════════════
# CODERCLAW BOT — Dedicated Claude Code controller via Telegram
# Persistent sessions: survives Cursor disconnects, resume from phone
# ═══════════════════════════════════════════════════════════════════════════

def _load_workspace_bootstrap() -> str:
    """
    Load workspace .md files for agent bootstrap context.
    Returns concatenated content of IDENTITY.md, USER.md, HEARTBEAT.md, TOOLS.md
    plus today's daily log. All files sized for token efficiency (~2KB each).
    """
    workspace = pathlib.Path("./workspace")
    if not workspace.exists():
        return ""

    bootstrap_files = ["IDENTITY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md"]
    parts = []

    # Load fixed bootstrap files
    for fname in bootstrap_files:
        fpath = workspace / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8")
                # Limit each file to 2000 chars to keep bootstrap token-efficient
                parts.append(f"## {fname}\n{content[:2000]}")
            except Exception as e:
                logger.warning(f"Failed to load {fname}: {e}")

    # Load today's daily log
    today = datetime.now().strftime("%Y-%m-%d")
    daily = workspace / f"{today}.md"
    if daily.exists():
        try:
            content = daily.read_text(encoding="utf-8")
            # Limit daily log to 1500 chars
            parts.append(f"## Daily Log ({today})\n{content[:1500]}")
        except Exception as e:
            logger.warning(f"Failed to load daily log: {e}")

    # Join with separators, max 8000 chars total
    bootstrap = "\n\n---\n\n".join(parts)
    return bootstrap[:8000]


async def _cc_send(chat_id, text: str, reply_to: int = None):
    """Send a message via CoderClaw bot."""
    if not CODERCLAW_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{CODERCLAW_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for i, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if reply_to and i == 0:
                payload["reply_to_message_id"] = reply_to
                payload["allow_sending_without_reply"] = True
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    payload.pop("parse_mode", None)
                    payload.pop("reply_to_message_id", None)
                    await client.post(url, json=payload)
            except Exception as e:
                logger.error(f"CoderClaw send error: {e}")


async def _cc_typing(chat_id):
    """Send typing indicator via CoderClaw bot."""
    if not CODERCLAW_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{CODERCLAW_BOT_TOKEN}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
    except Exception:
        pass


def _cc_get_session(chat_id) -> dict:
    """Load or create a CoderClaw session."""
    session_file = CODERCLAW_SESSIONS_DIR / f"{chat_id}.json"
    if session_file.exists():
        try:
            return json.loads(session_file.read_text())
        except Exception:
            pass
    return {
        "chat_id": chat_id,
        "claude_session_id": None,
        "project": ".",
        "history": [],
        "created_at": datetime.now(timezone.utc).isoformat()
    }


def _cc_save_session(chat_id, session: dict):
    """Save a CoderClaw session."""
    session_file = CODERCLAW_SESSIONS_DIR / f"{chat_id}.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(session, indent=2))


async def _cc_run_claude(prompt: str, session: dict, cwd: str = "/root") -> tuple:
    """
    Run Claude Code with --resume for session continuity.
    Returns (result_text, new_session_id).
    """
    try:
        import subprocess
        cmd = ["claude", "code", "--resume"]
        if session.get("claude_session_id"):
            cmd.extend(["--session", session["claude_session_id"]])

        # Combine prompt with workspace bootstrap for context
        bootstrap = _load_workspace_bootstrap()
        full_prompt = f"{bootstrap}\n\n---\n\nTask: {prompt}"

        # Run with timeout (5 min)
        result = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: subprocess.run(
                    cmd,
                    input=full_prompt,
                    text=True,
                    capture_output=True,
                    cwd=cwd,
                    timeout=300
                )
            ),
            timeout=320
        )

        # Parse session_id from Claude Code output if available
        session_id = None
        if "Session ID:" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Session ID:" in line:
                    session_id = line.split("Session ID:")[1].strip()
                    break

        # Return combined stdout/stderr (last 3800 chars to fit Telegram)
        result_text = result.stdout or result.stderr or "Claude Code ran but produced no output."

        # Try to parse JSON output if present
        try:
            lines = result_text.split("\n")
            for line in lines:
                if line.startswith("{"):
                    data = json.loads(line)
                    if "result" in data:
                        result_text = data["result"]
                        break
        except json.JSONDecodeError:
            pass

        return result_text[:3800], session_id

    except asyncio.TimeoutError:
        return "Claude Code timed out after 5 minutes. The task may still be running in the background.", session.get("claude_session_id")
    except Exception as e:
        return f"Error running Claude Code: {e}", session.get("claude_session_id")


@router.post("/coderclaw/webhook")
async def coderclaw_webhook(request: Request):
    """
    CoderClaw bot — Dedicated Claude Code controller via Telegram.

    Every message runs through Claude Code with --resume for session continuity.
    Returns 200 immediately and processes in background to prevent Telegram retries.
    Commands:
      /start — Welcome message
      /new — Start a fresh session (reset session_id)
      /status — Show running agents and session info
      /project <path> — Set working directory
      /output <job_id> — Get tmux agent output
      /spawn <task> — Spawn a long-running tmux agent (for big tasks)
      /kill <id|all> — Kill tmux agents
      Everything else — Runs through Claude Code with session resume
    """
    try:
        update = await request.json()
        if "message" not in update:
            return {"ok": True}

        # ── Dedup: reject retried updates (persistent, survives restarts) ──
        update_id = update.get("update_id")
        if _tg_dedup_check(update_id, bot="cc"):
            logger.info(f"CoderClaw dedup: skipping update_id {update_id}")
            return {"ok": True}

        message = update["message"]
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message.get("text", "")
        msg_id = message.get("message_id")

        if not text:
            return {"ok": True}

        # Owner-only
        if TELEGRAM_OWNER_ID and user_id != TELEGRAM_OWNER_ID:
            return {"ok": True}

        logger.info(f"CoderClaw from {user_id}: {text[:80]}")

        # ── Quick commands: handle inline, return fast ──
        quick_commands = ["/start", "/new", "/status", "/project", "/output", "/kill", "/remote"]
        is_quick = any(text.strip().lower().startswith(cmd) for cmd in quick_commands)

        if is_quick:
            # Handle quick commands inline (fast, no bg needed)
            await _cc_typing(chat_id)

        # Load session
        session = _cc_get_session(chat_id)

        # ── /start ──
        if text.strip().lower() == "/start":
            await _cc_send(chat_id, (
                "<b>CoderClaw — Claude Code via Telegram</b>\n\n"
                "Send any message and I'll run it through Claude Code on your VPS.\n\n"
                "<b>Commands:</b>\n"
                "/new — Fresh session\n"
                "/status — Running agents\n"
                "/remote — Start a web session (get URL to open in browser)\n"
                "/remote stop — Stop the remote session\n"
                "/project &lt;path&gt; — Set working directory\n"
                "/spawn &lt;task&gt; — Long-running tmux agent\n"
                "/output &lt;job_id&gt; — Get agent output\n"
                "/kill &lt;id|all&gt; — Kill agents\n\n"
                "Everything else goes straight to Claude Code with session persistence. "
                "Your conversation carries over even if Cursor disconnects."
            ), reply_to=msg_id)
            return {"ok": True}

        # ── /new ──
        if text.strip().lower() == "/new":
            session["claude_session_id"] = None
            session["history"] = []
            _cc_save_session(chat_id, session)
            await _cc_send(chat_id, "Session reset. Next message starts a fresh Claude Code conversation.", reply_to=msg_id)
            return {"ok": True}

        # ── /project <path> ──
        proj_match = _re_tg.match(r'^/project\s+(.+)', text.strip())
        if proj_match:
            new_path = proj_match.group(1).strip()
            if os.path.isdir(new_path):
                session["project"] = new_path
                _cc_save_session(chat_id, session)
                await _cc_send(chat_id, f"Working directory set to: <code>{new_path}</code>", reply_to=msg_id)
            else:
                await _cc_send(chat_id, f"Directory not found: {new_path}", reply_to=msg_id)
            return {"ok": True}

        # ── /status ──
        if text.strip().lower() == "/status":
            lines = [f"<b>CoderClaw Status</b>\n"]
            lines.append(f"Session ID: <code>{session.get('claude_session_id', 'none')}</code>")
            lines.append(f"Project: <code>{session.get('project', '/root')}</code>")
            lines.append(f"History: {len(session.get('history', []))} messages\n")

            try:
                spawner = get_spawner()
                agents = spawner.list_agents()
                if agents:
                    lines.append(f"<b>{len(agents)} tmux agents running:</b>")
                    for a in agents:
                        lines.append(f"  {a['job_id'] or a['window_name']} — {a['status']} ({a['runtime_human']})")
                else:
                    lines.append("No tmux agents running.")
            except Exception:
                lines.append("Could not check tmux agents.")

            await _cc_send(chat_id, "\n".join(lines), reply_to=msg_id)
            return {"ok": True}

        # ── /remote — Start Claude Code remote-control session (web URL) ──
        if text.strip().lower().startswith("/remote"):
            remote_arg = text.strip()[7:].strip().lower()

            # /remote stop — kill any running remote-control session
            if remote_arg in ("stop", "kill", "off"):
                try:
                    import subprocess as _sp
                    # Find and kill remote-control tmux pane
                    result = _sp.run(
                        ["tmux", "list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}"],
                        capture_output=True, text=True, timeout=5
                    )
                    killed = False
                    for line in result.stdout.strip().split("\n"):
                        if "claude" in line.lower():
                            parts = line.split()
                            if parts:
                                pane_id = parts[0]
                                # Check if it's the remote-control window
                                check = _sp.run(
                                    ["tmux", "capture-pane", "-t", pane_id, "-p"],
                                    capture_output=True, text=True, timeout=5
                                )
                                if "remote-control" in check.stdout.lower() or "Remote Control" in check.stdout:
                                    _sp.run(["tmux", "send-keys", "-t", pane_id, "C-c", ""], timeout=5)
                                    _sp.run(["tmux", "send-keys", "-t", pane_id, "exit", "Enter"], timeout=5)
                                    killed = True
                    # Also check for named window
                    _sp.run(["tmux", "kill-window", "-t", "remote-control"], capture_output=True, timeout=5)
                    await _cc_send(chat_id, "Remote session stopped." if killed else "No active remote session found.", reply_to=msg_id)
                except Exception as e:
                    await _cc_send(chat_id, f"Stop failed: {e}", reply_to=msg_id)
                return {"ok": True}

            # /remote — Start a new remote-control session
            try:
                import subprocess as _sp
                cwd = session.get("project", ".")

                # Kill any existing remote-control window first
                _sp.run(["tmux", "kill-window", "-t", "remote-control"], capture_output=True, timeout=5)

                # Ensure tmux server exists
                _sp.run(["tmux", "has-session", "-t", "openclaw"], capture_output=True, timeout=5)
                has_session = _sp.run(["tmux", "has-session", "-t", "openclaw"], capture_output=True, timeout=5).returncode == 0
                if not has_session:
                    _sp.run(["tmux", "new-session", "-d", "-s", "openclaw"], timeout=5)

                # Start remote-control in a new tmux window
                # Unset CLAUDECODE to avoid nested session error
                cmd = f"cd {cwd} && unset CLAUDECODE && claude remote-control --verbose --permission-mode bypassPermissions 2>&1 | tee /tmp/claude-remote-output.log"
                _sp.run(
                    ["tmux", "new-window", "-t", "openclaw", "-n", "remote-control", "-d", cmd],
                    timeout=10
                )

                # Wait for URL to appear in output
                await _cc_send(chat_id, "Starting remote session... waiting for URL (5s)", reply_to=msg_id)
                await asyncio.sleep(6)

                # Read the output to extract URL
                url = None
                try:
                    # Try the log file first
                    if os.path.exists("/tmp/claude-remote-output.log"):
                        with open("/tmp/claude-remote-output.log") as f:
                            log_content = f.read()
                        import re as _re_mod
                        url_match = _re_mod.search(r'(https://claude\.ai/code/session_[^\s]+)', log_content)
                        if url_match:
                            url = url_match.group(1)

                    # Fallback: capture from tmux pane
                    if not url:
                        capture = _sp.run(
                            ["tmux", "capture-pane", "-t", "openclaw:remote-control", "-p", "-S", "-50"],
                            capture_output=True, text=True, timeout=5
                        )
                        import re as _re_mod
                        url_match = _re_mod.search(r'(https://claude\.ai/code/session_[^\s]+)', capture.stdout)
                        if url_match:
                            url = url_match.group(1)
                except Exception as e:
                    logger.warning(f"Remote URL extraction failed: {e}")

                if url:
                    await _cc_send(chat_id, (
                        f"<b>Remote Session Ready</b>\n\n"
                        f"Open this URL in your browser or Claude app:\n"
                        f"<code>{url}</code>\n\n"
                        f"Working directory: <code>{cwd}</code>\n"
                        f"Full VPS access — files, git, MCP tools, everything.\n\n"
                        f"Stop with: /remote stop"
                    ), reply_to=msg_id)
                else:
                    # URL not found yet — might need more time
                    await _cc_send(chat_id, (
                        "<b>Remote session starting...</b>\n\n"
                        "Couldn't extract URL yet. Check in a few seconds:\n"
                        "/output remote-control\n\n"
                        "Or try: /remote stop and retry."
                    ), reply_to=msg_id)

            except Exception as e:
                await _cc_send(chat_id, f"Remote start failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── /spawn <task> — long-running tmux agent ──
        spawn_match = _re_tg.match(r'^/spawn\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if spawn_match:
            task = spawn_match.group(1).strip()
            try:
                spawner = get_spawner()
                job_id = f"cc-{int(time.time())}"
                cwd = session.get("project", "/root")
                prompt = (
                    f"You are CoderClaw, a Claude Code agent running on the VPS.\n"
                    f"Working directory: {cwd}\n"
                    f"Task from Miles via Telegram: {task}\n\n"
                    f"Do the work thoroughly. Commit and push when done. Write a summary."
                )
                pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, cwd=cwd, timeout_minutes=30)
                await _cc_send(chat_id, (
                    f"<b>Agent spawned in tmux</b>\n"
                    f"Job: <code>{job_id}</code>\n"
                    f"Task: {task[:300]}\n"
                    f"CWD: {cwd}\n\n"
                    f"Check output: /output {job_id}"
                ), reply_to=msg_id)
            except Exception as e:
                await _cc_send(chat_id, f"Spawn failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── /output <job_id> ──
        out_match = _re_tg.match(r'^/output\s+(\S+)', text.strip(), _re_tg.IGNORECASE)
        if out_match:
            job_id = out_match.group(1)
            output_file = f"./data/agent_outputs/openclaw-output-{job_id}.txt"
            if os.path.exists(output_file):
                with open(output_file) as f:
                    content = f.read()
                tail = content[-3000:] if len(content) > 3000 else content
                await _cc_send(chat_id, f"<b>Output {job_id}:</b>\n<pre>{html_escape(tail)}</pre>", reply_to=msg_id)
            else:
                # Try tmux pane capture
                try:
                    spawner = get_spawner()
                    output = spawner.collect_output("", job_id=job_id)
                    await _cc_send(chat_id, f"<b>Output {job_id}:</b>\n<pre>{html_escape(output[-3000:])}</pre>", reply_to=msg_id)
                except Exception:
                    await _cc_send(chat_id, f"No output found for {job_id}", reply_to=msg_id)
            return {"ok": True}

        # ── /kill <id|all> ──
        kill_match = _re_tg.match(r'^/kill\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if kill_match:
            target = kill_match.group(1).strip()
            try:
                spawner = get_spawner()
                if target.lower() == "all":
                    count = spawner.kill_all()
                    await _cc_send(chat_id, f"Killed {count} agents.", reply_to=msg_id)
                else:
                    killed = False
                    for a in spawner.list_agents():
                        if a["job_id"] == target or target in (a.get("pane_id", ""), a.get("window_name", "")):
                            spawner.kill_agent(a["pane_id"])
                            killed = True
                            break
                    await _cc_send(chat_id, f"{'Killed' if killed else 'Not found'}: {target}", reply_to=msg_id)
            except Exception as e:
                await _cc_send(chat_id, f"Kill failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── Slow path: return 200 immediately, process in background ──
        # This prevents Telegram from retrying after 60s timeout
        async def _cc_process_slow(chat_id, text, session, msg_id):
            """Background task for Claude Code execution (can take minutes)."""
            try:
                # ── Route big tasks to the OpenClaw job system ──
                job_keywords = ["build", "deploy", "refactor", "create", "implement", "fix all", "redesign", "migrate"]
                if any(kw in text.lower() for kw in job_keywords) and len(text) > 50:
                    _cc_job_created = None
                    try:
                        project_path = session.get("project", "/root")
                        project_name = os.path.basename(project_path.rstrip("/")) or "openclaw"
                        _cc_job_created = create_job(project=project_name, task=text, priority="P1")
                        await _cc_send(chat_id, (
                            f"<b>Task queued as job</b>\n"
                            f"Job ID: <code>{_cc_job_created.id}</code>\n"
                            f"Project: <code>{project_name}</code>\n"
                            f"Priority: P1\n\n"
                            f"This task is too large for inline execution. "
                            f"An agent will pick it up shortly.\n"
                            f"Check status: /status"
                        ), reply_to=msg_id)
                        return
                    except Exception as e:
                        if _cc_job_created:
                            # Job exists in queue — don't also run inline (prevents double-reply)
                            logger.warning(f"CoderClaw job {_cc_job_created.id} created but send failed: {e}")
                            await _cc_send(chat_id, f"Task queued (job {_cc_job_created.id})", reply_to=msg_id)
                            return
                        logger.warning(f"CoderClaw job routing failed, falling back to inline: {e}")

                # ── DEFAULT: Run through Claude Code with --resume ──
                cwd = session.get("project", "/root")
                await _cc_typing(chat_id)

                result, new_session_id = await _cc_run_claude(text, session, cwd=cwd)

                # Update session
                if new_session_id:
                    session["claude_session_id"] = new_session_id
                session["history"].append({"role": "user", "content": text, "ts": time.time()})
                session["history"].append({"role": "assistant", "content": result[:500], "ts": time.time()})
                if len(session["history"]) > 100:
                    session["history"] = session["history"][-60:]
                _cc_save_session(chat_id, session)

                await _cc_send(chat_id, result, reply_to=msg_id)
            except Exception as e:
                logger.error(f"CoderClaw background processing error: {e}")
                await _cc_send(chat_id, f"Error: {e}", reply_to=msg_id)

        asyncio.create_task(_cc_process_slow(chat_id, text, session, msg_id))
        return {"ok": True}  # Return immediately so Telegram doesn't retry

    except Exception as e:
        logger.error(f"CoderClaw webhook error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram messages — routes to Claude Code agents for build/fix commands."""
    try:
        update = await request.json()

        if "message" not in update:
            return {"ok": True}

        # ── Dedup: reject retried updates (persistent, survives restarts) ──
        update_id = update.get("update_id")
        if _tg_dedup_check(update_id, bot="tg"):
            logger.info(f"Telegram dedup: skipping update_id {update_id}")
            return {"ok": True}

        message = update["message"]
        chat_id = message["chat"]["id"]
        user_id = str(message["from"]["id"])
        text = message.get("text", "") or message.get("caption", "")
        msg_id = message.get("message_id")

        # Owner-only check (before any processing)
        if TELEGRAM_OWNER_ID and user_id != TELEGRAM_OWNER_ID:
            logger.info(f"Ignoring non-owner Telegram message from {user_id}")
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # PHOTO HANDLING — Vision analysis (ingredients, etc.)
        # ═══════════════════════════════════════════════
        if "photo" in message:
            # Telegram sends multiple sizes; pick the largest
            photo = message["photo"][-1]
            file_id = photo["file_id"]
            caption = message.get("caption", "")
            logger.info(f"📷 Photo from {user_id} (caption: {caption[:80] if caption else 'none'})")
            await _tg_typing(chat_id)

            async def _process_photo(chat_id, file_id, caption, msg_id):
                try:
                    b64, media_type = await _tg_download_photo(file_id)
                    await _tg_analyze_photo(chat_id, b64, media_type, caption, msg_id)
                except Exception as e:
                    logger.error(f"Photo processing error: {e}")
                    await _tg_send(chat_id, f"Failed to process photo: {e}", reply_to=msg_id)

            asyncio.create_task(_process_photo(chat_id, file_id, caption, msg_id))
            return {"ok": True}

        if not text:
            return {"ok": True}

        session_key = f"telegram:{user_id}:{chat_id}"
        logger.info(f"📱 Telegram from {user_id}: {text[:80]}")

        # Send typing indicator
        await _tg_typing(chat_id)

        # ═══════════════════════════════════════════════
        # 1. AGENT SPAWN — Build/fix/deploy/refactor commands
        # ═══════════════════════════════════════════════
        tg_agent_match = None
        for pattern, pattern_type in _CLAUDE_CODE_PATTERNS:
            match = _re_tg.match(pattern, text.strip(), _re_tg.IGNORECASE)
            if match:
                agent_match = match.group(1).strip() if match.groups() else text.strip()
                tg_agent_match = agent_match
                pattern_type_used = pattern_type
                break

        if tg_agent_match:
            try:
                spawner = get_spawner()

                # Parallel: multiple agents
                if pattern_type_used == "parallel":
                    tasks_str = tg_agent_match if tg_agent_match else text
                    tasks = [t.strip() for t in tasks_str.split(",") if t.strip()]
                    if not tasks:
                        await _tg_send(chat_id, "❌ No tasks found to run in parallel", reply_to=msg_id)
                        return {"ok": True}

                    pane_ids = []
                    for i, task in enumerate(tasks[:4]):  # Max 4 parallel
                        job_id = f"tg-parallel-{int(time.time())}-{i}"
                        prompt = (
                            f"You are an OpenClaw agent working on the VPS. Working directory: ./\n"
                            f"Task from Miles via Telegram: {task}\n\n"
                            f"Do the work. Be thorough. When done, write a summary."
                        )
                        try:
                            pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, timeout_minutes=30)
                            pane_ids.append(pane_id)
                        except Exception as e:
                            logger.error(f"Failed to spawn parallel task {i}: {e}")

                    if pane_ids:
                        await _tg_send(
                            chat_id,
                            f"<b>⚡ {len(pane_ids)} agents spawned in parallel</b>\n"
                            f"Tasks: {', '.join(str(t[:50]) for t in tasks)}\n\n"
                            f"Check output: <code>./autonomous.sh output &lt;job_id&gt;</code>",
                            reply_to=msg_id
                        )
                        return {"ok": True}
                    else:
                        await _tg_send(chat_id, "❌ Failed to spawn any agents", reply_to=msg_id)
                        return {"ok": True}

                else:
                    # Single agent task
                    job_id = f"tg-{int(time.time())}"
                    prompt = (
                        f"You are an OpenClaw agent working on the VPS. Working directory: ./\n"
                        f"Task from Miles via Telegram: {tg_agent_match}\n\n"
                        f"Do the work. Be thorough. When done, write a summary of what you did."
                    )
                    pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, timeout_minutes=30)

                    await _tg_send(
                        chat_id,
                        f"<b>⚡ Agent spawned</b>\n"
                        f"Job: <code>{job_id}</code>\n"
                        f"Task: {tg_agent_match[:300]}\n"
                        f"Pane: {pane_id}\n\n"
                        f"Check output: <code>./autonomous.sh output {job_id}</code>",
                        reply_to=msg_id
                    )
                    return {"ok": True}

            except Exception as e:
                logger.error(f"Agent spawn from Telegram failed: {e}")
                await _tg_send(chat_id, f"❌ Agent spawn failed: {e}", reply_to=msg_id)
                return {"ok": True}  # Don't fall through — already replied

        # ═══════════════════════════════════════════════
        # 2. TASK CREATION — "create task:", "todo:", "remind me to:"
        # ═══════════════════════════════════════════════
        tg_task_match = None
        for _p in _TASK_PATTERNS:
            _m = _re_tg.match(_p, text.strip(), _re_tg.IGNORECASE)
            if _m:
                tg_task_match = _m.group(1).strip()
                break

        if tg_task_match:
            try:
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r') as f:
                        tasks = json.load(f)
                else:
                    tasks = []
                routing = agent_router.select_agent(tg_task_match)
                new_task = {
                    "id": str(uuid.uuid4())[:8],
                    "title": tg_task_match[:200],
                    "description": text,
                    "status": "todo",
                    "agent": routing.get("agentId", "project_manager"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "telegram",
                    "session_key": session_key
                }
                tasks.append(new_task)
                with open(TASKS_FILE, 'w') as f:
                    json.dump(tasks, f, indent=2)

                tg_jm_job_id = None
                try:
                    tg_jm_job = create_job(project=new_task.get("title", "telegram-task"), task=text, priority="P1")
                    tg_jm_job_id = tg_jm_job.id
                except Exception:
                    pass

                task_response = (
                    f"✅ Task created: {tg_task_match[:200]}\n"
                    f"ID: {new_task['id']}"
                    + (f" | Job: {tg_jm_job_id}" if tg_jm_job_id else "")
                )
                broadcast_event({"type": "task_created", "agent": "project_manager",
                                 "message": f"Task from Telegram: {tg_task_match[:80]}"})
                await _tg_send(chat_id, task_response, reply_to=msg_id)
                return {"ok": True}
            except Exception as e:
                logger.error(f"Telegram task creation failed: {e}")
                await _tg_send(chat_id, f"❌ Task creation failed: {e}", reply_to=msg_id)
                return {"ok": True}  # Don't fall through

        # ═══════════════════════════════════════════════
        # 2.5. DAY PLANNER — "plan my day", "/plan", "day plan"
        # ═══════════════════════════════════════════════
        text_lower = text.strip().lower()
        if text_lower in ("plan my day", "/plan", "day plan", "plan", "what's my day", "daily plan"):
            async def _run_day_plan(chat_id, msg_id):
                try:
                    await _tg_typing(chat_id)
                    from agent_tools import _plan_my_day
                    plan = _plan_my_day("all")
                    await _tg_send(chat_id, plan, reply_to=msg_id)
                except Exception as e:
                    logger.error(f"Day plan error: {e}")
                    await _tg_send(chat_id, f"Failed to generate day plan: {e}", reply_to=msg_id)

            asyncio.create_task(_run_day_plan(chat_id, msg_id))
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 3. STATUS CHECK — "status", "agents", "what's running"
        # ═══════════════════════════════════════════════
        if text_lower in ("status", "/status", "what's running", "agents", "check agents"):
            try:
                spawner = get_spawner()
                agents = spawner.list_agents()
                if agents:
                    lines = [f"<b>🤖 {len(agents)} agents running</b>\n"]
                    for a in agents:
                        lines.append(f"• {a['job_id'] or a['window_name']} — {a['status']} ({a['runtime_human']})")
                    await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
                else:
                    await _tg_send(chat_id, "No agents running. Send a command to spawn one!", reply_to=msg_id)
                return {"ok": True}
            except Exception as e:
                await _tg_send(chat_id, f"Status check failed: {e}", reply_to=msg_id)
                return {"ok": True}

        # ═══════════════════════════════════════════════
        # 4. AGENT OUTPUT — "output JOB_ID"
        # ═══════════════════════════════════════════════
        output_match = _re_tg.match(r'^\s*output\s+(\S+)', text.strip(), _re_tg.IGNORECASE)
        if output_match:
            job_id = output_match.group(1)
            output_file = f"/tmp/openclaw-output-{job_id}.txt"
            if os.path.exists(output_file):
                with open(output_file, "r") as f:
                    content = f.read()
                # Last 2000 chars
                tail = content[-2000:] if len(content) > 2000 else content
                await _tg_send(chat_id, f"<b>Output for {job_id}:</b>\n<pre>{html_escape(tail)}</pre>", reply_to=msg_id)
            else:
                await _tg_send(chat_id, f"No output file for job {job_id}", reply_to=msg_id)
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 5. KILL AGENT — "kill JOB_ID" or "kill all"
        # ═══════════════════════════════════════════════
        kill_match = _re_tg.match(r'^\s*kill\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if kill_match:
            target = kill_match.group(1).strip()
            try:
                spawner = get_spawner()
                if target.lower() == "all":
                    count = spawner.kill_all()
                    await _tg_send(chat_id, f"Killed {count} agents.", reply_to=msg_id)
                else:
                    # Find agent by job_id
                    killed = False
                    for a in spawner.list_agents():
                        if a["job_id"] == target or target in (a.get("pane_id", ""), a.get("window_name", "")):
                            spawner.kill_agent(a["pane_id"])
                            killed = True
                            break
                    await _tg_send(chat_id, f"{'Killed' if killed else 'Not found'}: {target}", reply_to=msg_id)
            except Exception as e:
                await _tg_send(chat_id, f"Kill failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 5.5. BRICK BUILDER — AI-powered building suggestions
        # ═══════════════════════════════════════════════
        brick_match = None
        brick_action = None
        for pattern, action in _BRICK_BUILDER_PATTERNS:
            match = _re_tg.match(pattern, text.strip(), _re_tg.IGNORECASE)
            if match:
                brick_action = action
                brick_match = match.group(1).strip() if match.groups() and match.group(1) else None
                break

        if brick_action:
            async def _tg_process_brick_builder(chat_id, action, prompt, msg_id):
                try:
                    await _tg_typing(chat_id)
                    async with httpx.AsyncClient(timeout=30) as client:
                        if action == "suggest":
                            # Parse prompt into brick array (simple format: "brick type, x, y, z")
                            resp = await client.post(
                                "http://localhost:18789/brick-builder/ai/suggest",
                                json={
                                    "bricks": [],
                                    "context": prompt,
                                    "count": 3
                                }
                            )
                            resp.raise_for_status()
                            result = resp.json()
                            suggestion = result.get("suggestion", "No suggestion generated")
                            await _tg_send(chat_id, f"<b>🧱 Brick Suggestion</b>\n\n{suggestion}", reply_to=msg_id)
                        elif action == "complete":
                            resp = await client.post(
                                "http://localhost:18789/brick-builder/ai/complete",
                                json={
                                    "bricks": [],
                                    "context": prompt
                                }
                            )
                            resp.raise_for_status()
                            result = resp.json()
                            completion = result.get("completion", "No completion generated")
                            await _tg_send(chat_id, f"<b>🧱 Block Completion</b>\n\n{completion}", reply_to=msg_id)
                        elif action == "describe":
                            # Attempt to parse the prompt as JSON
                            import json as _json_brick
                            try:
                                build_data = _json_brick.loads(prompt)
                            except:
                                build_data = {"bricks": [], "name": prompt}
                            resp = await client.post(
                                "http://localhost:18789/brick-builder/ai/describe",
                                json=build_data
                            )
                            resp.raise_for_status()
                            result = resp.json()
                            description = result.get("description", "No description generated")
                            await _tg_send(chat_id, f"<b>🧱 Build Description</b>\n\n{description}", reply_to=msg_id)
                        elif action == "list":
                            resp = await client.get(
                                "http://localhost:18789/brick-builder/builds/list",
                                params={"limit": 10}
                            )
                            resp.raise_for_status()
                            result = resp.json()
                            builds = result.get("builds", [])
                            if builds:
                                lines = ["<b>🧱 Saved Builds</b>\n"]
                                for build in builds[:10]:
                                    name = build.get("name", "Unnamed")
                                    lines.append(f"• {name}")
                                await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
                            else:
                                await _tg_send(chat_id, "No saved builds yet. Try suggesting one!", reply_to=msg_id)
                except Exception as e:
                    logger.error(f"Brick Builder error: {e}")
                    await _tg_send(chat_id, f"Brick Builder error: {e}", reply_to=msg_id)

            if brick_match or brick_action == "list":
                asyncio.create_task(_tg_process_brick_builder(chat_id, brick_action, brick_match or "", msg_id))
                return {"ok": True}

        # ═══════════════════════════════════════════════
        # 6. NORMAL CHAT — Route through Claude for conversation
        # Runs in background to prevent Telegram retry duplicates
        # ═══════════════════════════════════════════════
        async def _tg_process_chat(chat_id, text, session_key, msg_id):
            try:
                session_history = save_session_history(session_key)
                messages_for_api = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session_history
                ]
                messages_for_api.append({"role": "user", "content": text})

                route_decision = agent_router.select_agent(text)
                agent_config = CONFIG.get("agents", {}).get(route_decision["agentId"], {})
                system_prompt = build_channel_system_prompt(agent_config)
                model = agent_config.get("model", "claude-opus-4-6")

                assistant_message = await call_model_with_escalation(
                    anthropic_client, model, system_prompt, messages_for_api
                )

                session_history.append({"role": "user", "content": text})
                session_history.append({"role": "assistant", "content": assistant_message})
                save_session_history(session_key, session_history)

                await _tg_send(chat_id, assistant_message, reply_to=msg_id)

            except Exception as e:
                logger.error(f"Telegram chat error: {e}")
                await _tg_send(chat_id, f"Error: {str(e)[:500]}", reply_to=msg_id)

        asyncio.create_task(_tg_process_chat(chat_id, text, session_key, msg_id))
        return {"ok": True}  # Return immediately so Telegram doesn't retry

    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"ok": False, "error": str(e)}
