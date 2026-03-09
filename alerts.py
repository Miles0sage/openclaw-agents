import hashlib
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

# --- Dedup cache: prevent identical/near-identical Telegram spam ---
# Key: hash of (job_id_prefix + message_category), Value: last sent timestamp
_SENT: dict[str, float] = {}
_SENT_MAX = 500          # max entries before pruning
_DEFAULT_COOLDOWN = 300  # 5 min: same job+category won't fire again within this window


def _dedup_key(text: str) -> str:
    """Stable key: first 40 chars of message (captures job_id + category)."""
    return hashlib.md5(text[:80].encode()).hexdigest()


def _should_send(key: str, cooldown: float) -> bool:
    now = time.monotonic()
    last = _SENT.get(key)
    if last is not None and (now - last) < cooldown:
        return False
    _SENT[key] = now
    # Prune oldest entries if cache grows too large
    if len(_SENT) > _SENT_MAX:
        oldest = sorted(_SENT, key=lambda k: _SENT[k])
        for k in oldest[:100]:
            del _SENT[k]
    return True


async def send_telegram(text: str, cooldown: float = _DEFAULT_COOLDOWN) -> None:
    """Send a Telegram message to the owner via Telegram Bot API.

    Deduplicates: the same message category (first 80 chars) won't fire again
    within `cooldown` seconds (default 5 min). This prevents job re-queue
    double-fires and rapid failure storms from spamming the phone.

    Pass cooldown=0 to bypass dedup (e.g. credit exhausted — always send).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_USER_ID", "")
    if not token or not chat_id:
        return
    if cooldown > 0:
        key = _dedup_key(text)
        if not _should_send(key, cooldown):
            return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
            # Retry without Markdown if parse error (e.g. unmatched backtick)
            if resp.status_code == 400:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
    except Exception:
        pass  # Never let alerts crash the runner
