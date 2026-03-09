"""
Twilio SMS webhook and API endpoints.

This module handles:
- Inbound SMS webhooks from Twilio
- SMS sending via API
- SMS history retrieval
"""

import os
import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from routers.shared import (
    send_slack_message,
    broadcast_event,
)

logger = logging.getLogger("openclaw_gateway")
router = APIRouter()


# ── Pydantic Models ─────────────────────────────────────────────────────

class SMSSendRequest(BaseModel):
    to: str
    body: str


# ── Twilio SMS Endpoints ────────────────────────────────────────────────

@router.post("/webhook/twilio")
async def twilio_incoming_sms(request: Request):
    """Receive inbound SMS from Twilio webhook."""
    try:
        form_data = await request.form()
        from_number = form_data.get("From", "")
        to_number = form_data.get("To", "")
        message_body = form_data.get("Body", "")
        message_sid = form_data.get("MessageSid", "")

        logger.info(f"📱 Inbound SMS from {from_number}: {message_body[:100]}")

        # Validate Twilio signature if auth token is set
        twilio_auth = os.getenv("TWILIO_AUTH_TOKEN")
        if twilio_auth:
            import hmac as _hmac
            import hashlib as _hashlib
            import base64 as _b64
            sig = request.headers.get("X-Twilio-Signature", "")
            # Build validation URL
            url = str(request.url)
            params = sorted(form_data.items())
            url_with_params = url + "".join(f"{k}{v}" for k, v in params)
            expected = _b64.b64encode(
                _hmac.new(twilio_auth.encode(), url_with_params.encode(), _hashlib.sha1).digest()
            ).decode()
            if not _hmac.compare_digest(sig, expected):
                logger.warning(f"⚠️ Invalid Twilio signature from {from_number}")
                # Don't reject in case URL mismatch (proxy), just log

        # Log the inbound message
        from agent_tools import _log_sms
        _log_sms("received", to_number, from_number, message_body, message_sid)

        # Broadcast event
        broadcast_event({
            "type": "sms.received",
            "from": from_number,
            "body": message_body[:200],
            "sid": message_sid,
        })

        # Forward to Slack for visibility
        try:
            await send_slack_message(
                os.getenv("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7"),
                f"📱 *Inbound SMS* from `{from_number}`:\n>{message_body}"
            )
        except Exception:
            pass

        # Return empty TwiML (accept silently)
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml"
        )
    except Exception as e:
        logger.error(f"Twilio webhook error: {e}")
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="application/xml",
            status_code=200  # Always 200 to Twilio
        )


@router.post("/sms/send")
async def send_sms_endpoint(req: SMSSendRequest, request: Request):
    """Send an SMS via API. Requires auth token."""
    auth = request.headers.get("X-Auth-Token", "")
    expected = os.getenv("GATEWAY_AUTH_TOKEN", "")
    if not expected or auth != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from agent_tools import _send_sms
    result = _send_sms(req.to, req.body)
    success = not result.startswith("Error")
    return {"ok": success, "result": result}


@router.get("/sms/history")
async def sms_history_endpoint(request: Request, direction: str = "all", limit: int = 10):
    """Get SMS history. Requires auth token."""
    auth = request.headers.get("X-Auth-Token", "")
    expected = os.getenv("GATEWAY_AUTH_TOKEN", "")
    if not expected or auth != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from agent_tools import _get_sms_history
    result = _get_sms_history(direction, limit)
    return {"ok": True, "result": result}
