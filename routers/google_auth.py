"""
Google OAuth, Gmail, and Calendar API router for OpenClaw.

Provides endpoints for:
- OAuth flow initialization and token exchange
- Gmail inbox, send, trash, label, and labels list operations
- Google Calendar read and write operations (today, upcoming, create, list)

All endpoints use the shared Google credentials located at:
  /root/.config/gmail/credentials.json (OAuth app credentials)
  /root/.config/gmail/token.json (user access tokens)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse

from routers.shared import logger

# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS & CONFIG
# ════════════════════════════════════════════════════════════════════════════

GOOGLE_CREDS_FILE = "/root/.config/gmail/credentials.json"
GOOGLE_TOKEN_DIR = "/root/.config/gmail"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

router = APIRouter(prefix="", tags=["google-auth"])

# ════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════


def _get_google_creds():
    """Load and refresh Google OAuth credentials."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest

    token_path = os.path.join(GOOGLE_TOKEN_DIR, "token.json")
    if not os.path.exists(token_path):
        raise HTTPException(status_code=500, detail="Google token not found. Run /oauth/start first.")

    with open(token_path) as f:
        token_data = json.load(f)

    # Merge client_id/client_secret from credentials.json if missing
    if "client_id" not in token_data or "client_secret" not in token_data:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        installed = creds_data.get("installed", creds_data.get("web", {}))
        token_data["client_id"] = installed["client_id"]
        token_data["client_secret"] = installed["client_secret"]
        token_data["token_uri"] = installed.get("token_uri", "https://oauth2.googleapis.com/token")
        # Save merged version for future loads
        with open(token_path, "w") as f:
            json.dump(token_data, f, indent=2)

    creds = Credentials.from_authorized_user_info(token_data, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        # Save refreshed token
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


# ════════════════════════════════════════════════════════════════════════════
# OAUTH ENDPOINTS — Google OAuth flow
# ════════════════════════════════════════════════════════════════════════════


@router.get("/oauth/start")
async def oauth_start():
    """Start Google OAuth flow — redirects back to /oauth/callback on this gateway."""
    try:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        creds = creds_data.get("installed", creds_data.get("web", {}))
        client_id = creds["client_id"]

        import urllib.parse
        redirect_uri = "https://<your-domain>/oauth/callback"
        params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        })
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{params}"
        gateway_url = "https://<your-domain>/oauth/exchange"
        html = f"""<!DOCTYPE html>
<html><head><title>OpenClaw — Google OAuth</title>
<style>body{{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#18181b;border:1px solid #3f3f46;border-radius:12px;padding:40px;max-width:600px;text-align:center}}
a{{color:#3b82f6;font-size:18px}}
.steps{{text-align:left;margin-top:20px;line-height:2}}
.steps b{{color:#22c55e}}
code{{background:#27272a;padding:2px 8px;border-radius:4px;font-size:13px}}
input{{width:100%;padding:12px;margin:10px 0;background:#27272a;border:1px solid #3f3f46;color:#fafafa;border-radius:8px;font-size:16px}}
button{{padding:12px 24px;background:#3b82f6;color:white;border:none;border-radius:8px;font-size:16px;cursor:pointer}}
button:hover{{background:#2563eb}}
.result{{margin-top:16px;padding:12px;border-radius:8px;display:none}}</style></head>
<body><div class="card">
<h1>OpenClaw OAuth</h1>
<div class="steps">
<b>Step 1:</b> <a href="{auth_url}" target="_blank">Click here to authorize with Google</a><br>
<b>Step 2:</b> Sign in and approve the permissions<br>
<b>Step 3:</b> Google will show you a code on screen — copy it<br>
<b>Step 4:</b> Paste the code below:
</div>
<form onsubmit="return submitCode()">
<input type="text" id="codeInput" placeholder="Paste the authorization code here..." autofocus>
<button type="submit">Save Token</button>
</form>
<div id="result" class="result"></div>
<script>
async function submitCode() {{
    const code = document.getElementById('codeInput').value.trim();
    const result = document.getElementById('result');
    if (!code) {{
        result.style.display = 'block';
        result.style.background = '#7f1d1d';
        result.textContent = 'Please paste the code from Google.';
        return false;
    }}
    try {{
        const resp = await fetch('{gateway_url}?code=' + encodeURIComponent(code));
        const data = await resp.json();
        if (data.status === 'ok') {{
            result.style.display = 'block';
            result.style.background = '#14532d';
            result.innerHTML = '&#9989; ' + data.message;
        }} else {{
            result.style.display = 'block';
            result.style.background = '#7f1d1d';
            result.textContent = 'Error: ' + (data.error || 'Unknown error');
        }}
    }} catch(e) {{
        result.style.display = 'block';
        result.style.background = '#7f1d1d';
        result.textContent = 'Network error: ' + e.message;
    }}
    return false;
}}
</script>
</div></body></html>"""
        return HTMLResponse(html)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/oauth/exchange")
async def oauth_exchange(code: str = None):
    """Exchange an OAuth code for tokens — Desktop client OOB flow."""
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)

    try:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        creds = creds_data.get("installed", creds_data.get("web", {}))

        import httpx as hx
        token_resp = hx.post(creds["token_uri"], data={
            "code": code,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "redirect_uri": "https://<your-domain>/oauth/callback",
            "grant_type": "authorization_code",
        }, timeout=15)
        token_data = token_resp.json()

        if "error" in token_data:
            return JSONResponse({
                "error": f"{token_data['error']}: {token_data.get('error_description', '')}"
            }, status_code=400)

        # Save tokens for both Gmail and Calendar MCP
        os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
        for fname in ("token.json", "calendar_token.json"):
            with open(os.path.join(GOOGLE_TOKEN_DIR, fname), "w") as f:
                json.dump(token_data, f, indent=2)

        logger.info("Google OAuth tokens saved successfully")
        scopes = token_data.get("scope", "").split()
        return {"status": "ok", "message": f"Authorized! Tokens saved. Scopes: {', '.join(scopes)}"}
    except Exception as e:
        logger.error(f"OAuth exchange error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/oauth/callback")
async def oauth_callback(code: str = None, error: str = None):
    """Handle Google OAuth redirect — exchanges code for tokens automatically."""
    if error:
        return HTMLResponse(f"""<!DOCTYPE html><html><head><title>OAuth Error</title>
<style>body{{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#18181b;border:1px solid #7f1d1d;border-radius:12px;padding:40px;max-width:500px;text-align:center}}</style></head>
<body><div class="card"><h1>OAuth Error</h1><p>{error}</p><a href="/oauth/start" style="color:#3b82f6">Try again</a></div></body></html>""", status_code=400)
    if code:
        # Exchange code for tokens using the callback redirect_uri
        try:
            with open(GOOGLE_CREDS_FILE) as f:
                creds_data = json.load(f)
            creds = creds_data.get("installed", creds_data.get("web", {}))

            import httpx as hx
            token_resp = hx.post(creds["token_uri"], data={
                "code": code,
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "redirect_uri": "https://<your-domain>/oauth/callback",
                "grant_type": "authorization_code",
            }, timeout=15)
            token_data = token_resp.json()

            if "error" in token_data:
                return HTMLResponse(f"""<!DOCTYPE html><html><head><title>Token Error</title>
<style>body{{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#18181b;border:1px solid #7f1d1d;border-radius:12px;padding:40px;max-width:500px;text-align:center}}</style></head>
<body><div class="card"><h1>Token Error</h1><p>{token_data['error']}: {token_data.get('error_description', '')}</p><a href="/oauth/start" style="color:#3b82f6">Try again</a></div></body></html>""", status_code=400)

            # Save tokens
            os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
            for fname in ("token.json", "calendar_token.json"):
                with open(os.path.join(GOOGLE_TOKEN_DIR, fname), "w") as f:
                    json.dump(token_data, f, indent=2)

            logger.info("Google OAuth tokens saved via callback")
            scopes = token_data.get("scope", "").split()
            return HTMLResponse(f"""<!DOCTYPE html><html><head><title>Success!</title>
<style>body{{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#18181b;border:1px solid #14532d;border-radius:12px;padding:40px;max-width:500px;text-align:center}}
h1{{color:#22c55e}}</style></head>
<body><div class="card"><h1>Connected!</h1><p>Google account linked successfully.</p><p>Scopes: {', '.join(s.split('/')[-1] for s in scopes)}</p><p>You can close this tab now.</p></div></body></html>""")
        except Exception as e:
            logger.error(f"OAuth callback error: {e}")
            return HTMLResponse(f"<h1>Error</h1><p>{e}</p>", status_code=500)
    return HTMLResponse("<h1>Missing code</h1>", status_code=400)


# ════════════════════════════════════════════════════════════════════════════
# GMAIL ENDPOINTS — Read/write Gmail messages
# ════════════════════════════════════════════════════════════════════════════


@router.get("/api/gmail/inbox")
async def api_gmail_inbox(limit: int = 10, unread_only: bool = True):
    """Get Gmail inbox messages. Returns subject, from, snippet, date, read status."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)

        query = "in:inbox"
        if unread_only:
            query += " is:unread"

        results = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
        msg_ids = results.get("messages", [])

        messages = []
        for msg_ref in msg_ids[:limit]:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "snippet": msg.get("snippet", ""),
                "date": headers.get("Date", ""),
                "is_read": "UNREAD" not in msg.get("labelIds", []),
            })

        return {"messages": messages, "total": len(messages)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gmail inbox error: {e}")
        return JSONResponse({"error": str(e), "messages": []}, status_code=500)


@router.post("/api/gmail/send")
async def api_gmail_send(request: Request):
    """Send an email via Gmail."""
    try:
        from googleapiclient.discovery import build
        import base64
        from email.mime.text import MIMEText

        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)
        body = await request.json()

        to = body.get("to")
        subject = body.get("subject", "")
        message_text = body.get("body", "")

        if not to:
            return JSONResponse({"error": "to address required"}, status_code=400)

        msg = MIMEText(message_text)
        msg["to"] = to
        msg["subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()

        return {"success": True, "message_id": sent.get("id"), "thread_id": sent.get("threadId")}
    except Exception as e:
        logger.error(f"Gmail send error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/gmail/trash")
async def api_gmail_trash(request: Request):
    """Move emails to trash. Accepts a list of message IDs."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)
        body = await request.json()
        message_ids = body.get("message_ids", [])

        if not message_ids:
            return JSONResponse({"error": "message_ids required"}, status_code=400)

        trashed = []
        for mid in message_ids[:50]:  # Cap at 50 to prevent abuse
            try:
                service.users().messages().trash(userId="me", id=mid).execute()
                trashed.append(mid)
            except Exception as e:
                logger.warning(f"Failed to trash {mid}: {e}")

        return {"success": True, "trashed": len(trashed), "message_ids": trashed}
    except Exception as e:
        logger.error(f"Gmail trash error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/gmail/label")
async def api_gmail_label(request: Request):
    """Add or remove labels on emails."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)
        body = await request.json()

        message_ids = body.get("message_ids", [])
        add_labels = body.get("add_labels", [])      # e.g. ["IMPORTANT", "STARRED"]
        remove_labels = body.get("remove_labels", []) # e.g. ["UNREAD", "INBOX"]

        if not message_ids:
            return JSONResponse({"error": "message_ids required"}, status_code=400)

        modified = []
        label_body = {}
        if add_labels:
            label_body["addLabelIds"] = add_labels
        if remove_labels:
            label_body["removeLabelIds"] = remove_labels

        for mid in message_ids[:50]:
            try:
                service.users().messages().modify(userId="me", id=mid, body=label_body).execute()
                modified.append(mid)
            except Exception as e:
                logger.warning(f"Failed to label {mid}: {e}")

        return {"success": True, "modified": len(modified), "message_ids": modified}
    except Exception as e:
        logger.error(f"Gmail label error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/gmail/labels")
async def api_gmail_labels():
    """List all Gmail labels."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)
        results = service.users().labels().list(userId="me").execute()
        labels = [{"id": l["id"], "name": l["name"], "type": l.get("type", "")} for l in results.get("labels", [])]
        return {"labels": labels, "total": len(labels)}
    except Exception as e:
        logger.error(f"Gmail labels error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ════════════════════════════════════════════════════════════════════════════
# CALENDAR ENDPOINTS — Read/write Google Calendar events
# ════════════════════════════════════════════════════════════════════════════


@router.get("/api/calendar/today")
async def api_calendar_today():
    """Get today's calendar events from ALL calendars."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)

        # Use Arizona time (MST, UTC-7, no daylight saving)
        from zoneinfo import ZoneInfo
        az = ZoneInfo("America/Phoenix")
        now_local = datetime.now(az)
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_of_day = now_local.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        # Query ALL calendars, not just primary
        cal_list = service.calendarList().list().execute()
        events = []
        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            try:
                results = service.events().list(
                    calendarId=cal_id,
                    timeMin=start_of_day,
                    timeMax=end_of_day,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=20,
                ).execute()
                for item in results.get("items", []):
                    start = item.get("start", {})
                    end = item.get("end", {})
                    events.append({
                        "id": item.get("id", ""),
                        "summary": item.get("summary", "(no title)"),
                        "start": start.get("dateTime", start.get("date", "")),
                        "end": end.get("dateTime", end.get("date", "")),
                        "location": item.get("location", ""),
                        "calendar": cal_name,
                    })
            except Exception:
                pass  # Skip calendars we can't read

        events.sort(key=lambda e: e.get("start", ""))
        return {"events": events, "total": len(events)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar today error: {e}")
        return JSONResponse({"error": str(e), "events": []}, status_code=500)


@router.get("/api/calendar/upcoming")
async def api_calendar_upcoming(days: int = 7):
    """Get upcoming calendar events for the next N days."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)

        from zoneinfo import ZoneInfo
        az = ZoneInfo("America/Phoenix")
        now = datetime.now(az)
        end = now + timedelta(days=days)

        # Query ALL calendars
        cal_list = service.calendarList().list().execute()
        events = []
        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            try:
                results = service.events().list(
                    calendarId=cal_id,
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
                for item in results.get("items", []):
                    start = item.get("start", {})
                    end_t = item.get("end", {})
                    events.append({
                        "id": item.get("id", ""),
                        "summary": item.get("summary", "(no title)"),
                        "start": start.get("dateTime", start.get("date", "")),
                        "end": end_t.get("dateTime", end_t.get("date", "")),
                        "location": item.get("location", ""),
                        "calendar": cal_name,
                    })
            except Exception:
                pass

        events.sort(key=lambda e: e.get("start", ""))
        return {"events": events, "total": len(events)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar upcoming error: {e}")
        return JSONResponse({"error": str(e), "events": []}, status_code=500)


@router.post("/api/calendar/create")
async def api_calendar_create(request: Request):
    """Create a new Google Calendar event."""
    try:
        from googleapiclient.discovery import build
        from zoneinfo import ZoneInfo
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)
        body = await request.json()

        summary = body.get("summary", "New Event")
        start_time = body.get("start")  # ISO format, e.g. "2026-02-26T09:00:00"
        end_time = body.get("end")      # ISO format
        location = body.get("location", "")
        description = body.get("description", "")
        calendar_id = body.get("calendar_id", "primary")

        if not start_time or not end_time:
            return JSONResponse({"error": "start and end times required"}, status_code=400)

        # Default to Arizona timezone if no timezone offset in the time string
        tz = "America/Phoenix"
        event = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": tz},
            "end": {"dateTime": end_time, "timeZone": tz},
        }

        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        return {"success": True, "event_id": created.get("id"), "link": created.get("htmlLink", "")}
    except Exception as e:
        logger.error(f"Calendar create error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/calendar/event")
async def api_calendar_delete(event_id: str, calendar_id: str = "primary"):
    """Delete or decline a single calendar event instance. For recurring events, this deletes only the specified instance."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {"success": True, "deleted": event_id}
    except Exception as e:
        logger.error(f"Calendar delete error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/calendar/list")
async def api_calendar_list():
    """List all Google Calendar calendars."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)
        results = service.calendarList().list().execute()
        cals = [{"id": c["id"], "name": c.get("summary", ""), "access": c.get("accessRole", "")} for c in results.get("items", [])]
        return {"calendars": cals, "total": len(cals)}
    except Exception as e:
        logger.error(f"Calendar list error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
