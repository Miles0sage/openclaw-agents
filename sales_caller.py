"""
sales_caller.py — AI outbound sales calls via Vapi + ElevenLabs

Makes outbound calls to leads found by lead_finder.py.
The AI introduces OpenClaw, pitches services, handles objections,
and books meetings — all automatically.

Usage:
    from sales_caller import call_lead, call_leads_batch
    result = await call_lead(phone="+19285551234", business_name="Mountain Grill", business_type="restaurant")
    results = await call_leads_batch(lead_ids=["lead-123", "lead-456"])
"""

import os
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("sales_caller")

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

VAPI_API_KEY = os.getenv("VAPI_API_KEY", "2fb71a28-8c1e-49b3-bb38-1ab220c8262b")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "de6aa877-4949-4973-ac9b-0bdfc1a89044")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "iP95p4xoKVk53GoZ742B")  # ElevenLabs turbo v2.5 voice (same as Barber CRM assistant)
VAPI_BASE_URL = "https://api.vapi.ai"
CALL_LOG_DIR = "os.environ.get("OPENCLAW_DATA_DIR", "./data")/calls"
LEADS_DIR = "os.environ.get("OPENCLAW_DATA_DIR", "./data")/leads"

# Sales caller identity
CALLER_NAME = "Chris"  # AI caller name — charming, down-to-earth
COMPANY_NAME = "OpenClaw"
CALLBACK_NUMBER = "(520) 491-0222"  # Miles' real number for callbacks


def _get_sales_prompt(business_name: str, business_type: str, owner_name: str = "") -> str:
    """Build a sales system prompt tailored to the business type."""

    owner_greeting = f"Ask for {owner_name} by name. If someone else answers, say 'Hey is {owner_name} around?'" if owner_name else "Ask if the owner or manager is available in a casual way."

    type_hooks = {
        "restaurant": (
            f"You helped build the online ordering system for Delhi Palace — an Indian restaurant here in Flagstaff. "
            f"They used to lose money on DoorDash and Grubhub fees — like 30% per order gone. Now customers order "
            f"straight from their website, kitchen gets it on a screen instantly, no phone mistakes. They kept all that money. "
            f"You also built an AI receptionist for Surgeon Cuts barbershop that books appointments 24/7.\n\n"
            f"PAIN POINTS TO HIT FOR RESTAURANTS:\n"
            f"- 'How much are you guys paying DoorDash or Grubhub? Like 25-30% per order? That's brutal.'\n"
            f"- 'Do you ever get wrong phone orders? Like someone says medium and you hear large?'\n"
            f"- 'When it's slammed on a Friday night, who's answering the phone? Nobody, right? That's lost money.'\n"
            f"- 'We built a system where your menu is online, people order themselves, it goes straight to the kitchen screen. No middleman.'\n"
            f"Drop the case studies naturally — 'we've done this for a couple spots around town.'"
        ),
        "barbershop": (
            f"You built the AI phone receptionist for Surgeon Cuts barbershop right here in Flagstaff. "
            f"It picks up every call, books appointments, tells people about services and prices — "
            f"the barbers don't even have to put down their clippers. It works 24/7, even at midnight when "
            f"some guy decides he needs a fade for tomorrow's date.\n\n"
            f"PAIN POINTS TO HIT FOR BARBERSHOPS:\n"
            f"- 'How many calls do you think you miss when you're mid-cut? Like you're blending a fade and the phone rings — you can't exactly stop.'\n"
            f"- 'Do you ever lose walk-ins because people called first and nobody picked up so they went somewhere else?'\n"
            f"- 'Are you still doing the whole DM-to-book thing on Instagram? That's a lot of back and forth.'\n"
            f"- 'The AI we built for Surgeon Cuts picks up every single call. Books the appointment. Tells them prices. Done. Barbers never touch the phone.'\n"
            f"Also mention Delhi Palace — 'we work with a few local spots, not just barbers.'"
        ),
        "dental": (
            f"You built tech for local Flagstaff businesses — an AI receptionist for Surgeon Cuts barbershop "
            f"and an online ordering system for Delhi Palace restaurant. "
            f"For dental, this is where it really shines.\n\n"
            f"PAIN POINTS TO HIT FOR DENTAL OFFICES:\n"
            f"- 'How many calls go to voicemail during lunch or when the front desk is with a patient? Every missed call is a new patient going to the dentist down the street.'\n"
            f"- 'Does your team spend half their day on the phone doing scheduling? That's expensive — you're paying a skilled person to be a phone operator.'\n"
            f"- 'The AI receptionist we build answers every call, books appointments based on your real availability, handles rescheduling, even answers insurance questions.'\n"
            f"- 'Your front desk staff can actually focus on the patients in the office instead of being chained to the phone.'\n"
            f"- 'New patient calls at 8pm? AI picks up, books them, confirms next day. Instead of that lead going to the dentist who answered first.'"
        ),
        "auto": (
            f"You've built tech for local Flagstaff businesses — online ordering for Delhi Palace restaurant, "
            f"AI receptionist for Surgeon Cuts barbershop. Auto shops have a huge opportunity.\n\n"
            f"PAIN POINTS TO HIT FOR AUTO SHOPS:\n"
            f"- 'When someone Googles \"oil change Flagstaff\" or \"mechanic near me,\" does your shop come up? Because that's where 90% of new customers start.'\n"
            f"- 'Can people book an appointment online right now, or do they have to call during business hours? Because a lot of people want to book at 10pm from their couch.'\n"
            f"- 'Do you guys still do estimates over the phone? We can build a system where customers describe the issue online, upload a photo even, and you send a quote — saves you 20 minutes per call.'\n"
            f"- 'We built an AI receptionist for a barbershop in town — answers every call, books appointments. Same thing works for auto — oil changes, tire rotations, inspections, all bookable 24/7.'\n"
            f"- 'Plus we build websites that actually rank on Google. Not just a pretty page — one that shows up when people search.'"
        ),
        "real_estate": (
            f"You've built AI systems for local businesses — a receptionist for Surgeon Cuts barbershop, "
            f"ordering system for Delhi Palace restaurant. Real estate is where AI gets really powerful.\n\n"
            f"PAIN POINTS TO HIT FOR REAL ESTATE:\n"
            f"- 'How many buyer leads call at 8pm or on a Sunday? And what happens — voicemail? That lead is calling three other agents too. First one to actually talk to them wins.'\n"
            f"- 'We can set up an AI that answers those calls instantly — qualifies the buyer, answers questions about your listings, and books a showing. All while you're at dinner.'\n"
            f"- 'Do you use a CRM right now? A lot of agents have leads scattered across texts, emails, sticky notes. We build a system where everything's in one place.'\n"
            f"- 'The AI doesn't just pick up — it knows your listings. Square footage, price, neighborhood, schools. It can actually have a real conversation.'\n"
            f"- 'Think about it — you're basically cloning yourself for the boring stuff so you can focus on closings.'"
        ),
    }

    type_hook = type_hooks.get(business_type, type_hooks["restaurant"])

    return f"""You are {CALLER_NAME}. You work with a small tech company in Flagstaff, Arizona called {COMPANY_NAME}.

You're calling {business_name}. {owner_greeting}

HOW YOU TALK:
- You sound like a real person, not a robot. Use "um," "uh," "like," "honestly," "you know" naturally.
- You're warm and a little playful — crack a light joke if the moment is right.
- Keep sentences SHORT. Real people don't talk in paragraphs.
- React to what they say — laugh, agree, empathize. Don't just bulldoze through a script.
- You're a friendly local guy, not a telemarketer. Think "buddy recommending something" not "sales pitch."
- If they sound busy or annoyed, acknowledge it immediately: "I can tell you're slammed, I'll be super quick."
- Use their name naturally — but not too much, that's creepy.
- Pause sometimes. Let them talk. Don't fill every silence.

YOUR STORY:
{type_hook}

THE CONVERSATION:
1. Quick intro — who you are, you're local, you'll be fast
2. Drop the case study casually — "so we just did this thing for Delhi Palace" or "we built this AI receptionist for a barbershop in town"
3. Connect it to THEIR business — "and I was thinking, something like that could really work for you guys"
4. The ask — "would you be down for a quick 10-minute coffee chat this week? I can show you what we built, totally no pressure"
5. If they're interested — lock in a day and time. Say "my buddy Miles runs the company, he'd love to meet you"

PRICING (only if they ask):
- "Honestly it depends on what you need. But we're not some big agency charging crazy money — we keep it real for local businesses."
- "Most of our stuff pays for itself pretty quick. Like the restaurant ordering system — they stopped losing 30% to DoorDash, so it basically paid for itself month one."
- Never give exact numbers on the call. That's for the meeting.

IF THEY SAY NO:
- "Totally fair! Hey I appreciate you taking a sec. If anything ever comes up, we're right here in town."
- Never push. Never guilt trip. Be genuinely cool about it.

IF YOU HIT VOICEMAIL:
- Keep it under 20 seconds
- "Hey, this is {CALLER_NAME} — I work with a tech company here in Flagstaff called {COMPANY_NAME}. We just built some cool stuff for a couple local businesses and I wanted to see if you'd be interested in a quick chat. No pressure at all. Give me a ring back at {CALLBACK_NUMBER} whenever works. Have a good one!"

RULES:
- NEVER say "I'm an AI" or "I'm a virtual assistant" — you're {CALLER_NAME}, period
- NEVER be pushy, aggressive, or desperate
- Keep the call under 3 minutes unless they're genuinely engaged and chatting
- If they schedule a meeting, confirm day/time and mention Miles will be there
- Match their energy — if they're chill, be chill. If they're all business, be concise.
"""


def _get_first_message(business_name: str, owner_name: str = "", business_type: str = "") -> str:
    """Opening line for the call — tailored to business type."""
    if owner_name:
        base = f"Hey, is this {owner_name}? Oh cool — hey, this is Chris. I work with a small tech company here in Flagstaff."
    else:
        base = f"Hey! How's it going? This is Chris — I work with a tech company here in Flagstaff. Is the owner or manager around by any chance?"

    # Add a type-specific hook to the opener so it's immediately relevant
    type_openers = {
        "restaurant": " Got like one minute? I just helped a restaurant in town save a ton on delivery app fees and wanted to see if you guys might be interested in something similar.",
        "barbershop": " Got like one minute? We just built something pretty cool for a barbershop here in town and I thought you guys might dig it.",
        "dental": " Got like one minute? We've been helping local businesses with their phones and I had an idea for your office.",
        "auto": " Got like one minute? We help local shops get more customers through Google and online booking — thought I'd reach out.",
        "real_estate": " Got like one minute? We built an AI that answers buyer calls after hours and books showings — thought you might find it interesting.",
    }
    return base + type_openers.get(business_type, " Got like one minute? I promise I'll be quick.")


async def call_lead(
    phone: str,
    business_name: str,
    business_type: str = "restaurant",
    owner_name: str = "",
    lead_id: str = "",
) -> dict:
    """
    Make an outbound sales call to a lead.

    Args:
        phone: Phone number to call (E.164 or US format)
        business_name: Name of the business
        business_type: Type (restaurant, barbershop, dental, auto, real_estate)
        owner_name: Owner's name if known
        lead_id: Optional lead ID to link the call

    Returns:
        dict with call_id, status, etc.
    """
    if not VAPI_API_KEY:
        return {"error": "VAPI_API_KEY not set"}

    if not VAPI_PHONE_NUMBER_ID:
        return {"error": "VAPI_PHONE_NUMBER_ID not set. Get it from Vapi dashboard > Phone Numbers."}

    # Normalize phone number to E.164
    phone_clean = _normalize_phone(phone)
    if not phone_clean:
        return {"error": f"Invalid phone number: {phone}"}

    # Build the sales assistant config
    system_prompt = _get_sales_prompt(business_name, business_type, owner_name)
    first_message = _get_first_message(business_name, owner_name, business_type)

    payload = {
        "assistant": {
            "name": f"OpenClaw Sales — {business_name}",
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "messages": [{"role": "system", "content": system_prompt}],
            },
            "voice": {
                "provider": "11labs",
                "voiceId": ELEVENLABS_VOICE_ID,
                "stability": 0.7,
                "similarityBoost": 0.8,
            },
            "firstMessage": first_message,
            "endCallMessage": "Thanks for your time! Have a great day.",
            "maxDurationSeconds": 300,  # 5 min max
            "backgroundSound": "off",
            "silenceTimeoutSeconds": 30,
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_clean,
            "name": owner_name or business_name,
        },
    }

    logger.info(f"Calling {business_name} at {phone_clean} (type: {business_type})")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{VAPI_BASE_URL}/call",
                headers={
                    "Authorization": f"Bearer {VAPI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if resp.status_code in (200, 201, 202):
                call_data = resp.json()
                call_id = call_data.get("id", "unknown")

                # Log the call
                _log_call(call_id, phone_clean, business_name, business_type, lead_id, "initiated")

                # Update lead status
                if lead_id:
                    _update_lead_status(lead_id, "called", call_id)

                logger.info(f"Call initiated: {call_id} to {business_name}")
                return {
                    "success": True,
                    "call_id": call_id,
                    "phone": phone_clean,
                    "business_name": business_name,
                    "status": call_data.get("status", "initiated"),
                }
            else:
                error_msg = resp.text[:500]
                logger.error(f"Vapi call failed ({resp.status_code}): {error_msg}")
                return {
                    "success": False,
                    "error": f"Vapi API error {resp.status_code}: {error_msg}",
                    "phone": phone_clean,
                    "business_name": business_name,
                }

    except Exception as e:
        logger.error(f"Call to {business_name} failed: {e}")
        return {"success": False, "error": str(e), "business_name": business_name}


async def call_leads_batch(
    lead_ids: list[str] = None,
    business_type: str = None,
    location: str = None,
    limit: int = 5,
    delay_seconds: int = 60,
) -> list[dict]:
    """
    Call multiple leads in sequence with a delay between each.

    Args:
        lead_ids: Specific lead IDs to call
        business_type: Filter leads by type
        location: Filter leads by location
        limit: Max calls to make
        delay_seconds: Wait time between calls (default 60s)

    Returns:
        List of call results
    """
    import asyncio

    # Load leads
    leads = _load_leads(lead_ids, business_type, limit)

    if not leads:
        return [{"error": "No callable leads found (need phone numbers)"}]

    results = []
    for i, lead in enumerate(leads):
        phone = lead.get("phone", "")
        if not phone:
            results.append({"skipped": True, "business_name": lead.get("business_name"), "reason": "no phone"})
            continue

        result = await call_lead(
            phone=phone,
            business_name=lead.get("business_name", "Unknown"),
            business_type=lead.get("business_type", "restaurant"),
            owner_name=lead.get("owner_name", ""),
            lead_id=lead.get("lead_id", ""),
        )
        results.append(result)

        # Wait between calls (don't spam)
        if i < len(leads) - 1:
            logger.info(f"Waiting {delay_seconds}s before next call...")
            await asyncio.sleep(delay_seconds)

    return results


async def get_call_status(call_id: str) -> dict:
    """Check the status of a call."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{VAPI_BASE_URL}/call/{call_id}",
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Status check failed: {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


async def list_recent_calls(limit: int = 10) -> list[dict]:
    """List recent outbound calls from the log."""
    log_path = os.path.join(CALL_LOG_DIR, "calls.jsonl")
    if not os.path.exists(log_path):
        return []
    calls = []
    with open(log_path, "r") as f:
        for line in f:
            if line.strip():
                calls.append(json.loads(line))
    calls.reverse()
    return calls[:limit]


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format (+1XXXXXXXXXX)."""
    import re
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) > 11:
        return f"+{digits}"
    return ""


def _log_call(call_id: str, phone: str, business_name: str, business_type: str, lead_id: str, status: str):
    """Log call to JSONL."""
    Path(CALL_LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(CALL_LOG_DIR, "calls.jsonl")
    entry = {
        "call_id": call_id,
        "phone": phone,
        "business_name": business_name,
        "business_type": business_type,
        "lead_id": lead_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _update_lead_status(lead_id: str, status: str, call_id: str = ""):
    """Update a lead's status after calling."""
    for fname in os.listdir(LEADS_DIR):
        if fname.endswith(".json"):
            fpath = os.path.join(LEADS_DIR, fname)
            try:
                with open(fpath, "r") as f:
                    lead = json.load(f)
                if lead.get("lead_id") == lead_id:
                    lead["status"] = status
                    lead["last_call_id"] = call_id
                    lead["last_called_at"] = datetime.now(timezone.utc).isoformat()
                    with open(fpath, "w") as f:
                        json.dump(lead, f, indent=2)
                    return
            except Exception:
                continue


def _load_leads(lead_ids: list[str] = None, business_type: str = None, limit: int = 5) -> list[dict]:
    """Load leads from disk, filtered by IDs or type."""
    if not os.path.exists(LEADS_DIR):
        return []

    leads = []
    for fname in sorted(os.listdir(LEADS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(LEADS_DIR, fname)
        try:
            with open(fpath, "r") as f:
                lead = json.load(f)

            # Filter by IDs if specified
            if lead_ids and lead.get("lead_id") not in lead_ids:
                continue

            # Filter by type
            if business_type and business_type.lower() not in lead.get("business_type", "").lower():
                continue

            # Only include leads with phone numbers that haven't been called yet
            if lead.get("phone") and lead.get("status") != "called":
                leads.append(lead)

        except Exception:
            continue

    return leads[:limit]
