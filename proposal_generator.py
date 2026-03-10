"""
Proposal Generator — Auto-generate branded HTML client proposals for OpenClaw.

Generates professional single-file HTML proposals with embedded CSS,
tailored to the client's business type and selected services.

Data:
  - Proposals saved to data/proposals/{slug}_{timestamp}.html
  - Index at data/proposals/proposals.jsonl
"""

import json
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("proposal_generator")

# ─── Constants ────────────────────────────────────────────────────────────────

DATA_DIR = Path("./data/proposals")
INDEX_PATH = DATA_DIR / "proposals.jsonl"

VALID_BUSINESS_TYPES = ["restaurant", "barbershop", "dental", "auto", "realestate", "other"]
VALID_SERVICES = ["receptionist", "website", "crm", "full_package"]

# ─── Service Catalog ──────────────────────────────────────────────────────────

SERVICE_CATALOG = {
    "receptionist": {
        "name": "AI Receptionist",
        "tagline": "Never miss a call again",
        "price": 1500,
        "monthly": 200,
        "timeline_days": 3,
        "scope": [
            "Custom AI voice agent trained on your business",
            "24/7 phone answering with natural conversation",
            "Appointment booking and calendar integration",
            "Call routing and message taking",
            "SMS follow-up automation",
        ],
        "deliverables": [
            "Dedicated phone number with AI receptionist",
            "Custom voice profile and personality",
            "Integration with your scheduling system",
            "Real-time call dashboard and analytics",
            "Staff training session (30 min)",
        ],
    },
    "website": {
        "name": "Custom Website",
        "tagline": "Your digital storefront, done right",
        "price": 2500,
        "monthly": 100,
        "timeline_days": 5,
        "scope": [
            "Modern, mobile-first responsive design",
            "SEO-optimized pages and metadata",
            "Online ordering or booking integration",
            "Google Maps and business info integration",
            "Performance-optimized (90+ Lighthouse score)",
        ],
        "deliverables": [
            "Custom-designed website (up to 8 pages)",
            "Domain setup and SSL certificate",
            "Google Business Profile optimization",
            "Contact forms and call-to-action buttons",
            "Content management training (30 min)",
        ],
    },
    "crm": {
        "name": "Customer Management System",
        "tagline": "Know your customers, grow your business",
        "price": 3000,
        "monthly": 150,
        "timeline_days": 5,
        "scope": [
            "Custom CRM tailored to your business workflow",
            "Customer database with profiles and history",
            "Automated appointment reminders (SMS/email)",
            "Revenue tracking and analytics dashboard",
            "Staff management and scheduling",
        ],
        "deliverables": [
            "Production-ready CRM application",
            "Admin dashboard with real-time analytics",
            "Mobile-responsive interface for staff",
            "Data import from existing systems",
            "Full team training session (1 hour)",
        ],
    },
    "full_package": {
        "name": "Full Digital Transformation",
        "tagline": "Everything your business needs to dominate online",
        "price": 5500,
        "monthly": 350,
        "timeline_days": 10,
        "scope": [
            "AI Receptionist with custom voice agent",
            "Custom website with online ordering/booking",
            "Full CRM with customer management",
            "Cross-system integration (website + CRM + receptionist)",
            "Ongoing optimization and support",
        ],
        "deliverables": [
            "Complete AI receptionist setup",
            "Custom-designed website (up to 12 pages)",
            "Full CRM with analytics dashboard",
            "All systems integrated and talking to each other",
            "Priority support channel",
            "Monthly performance review (first 3 months)",
        ],
    },
}

# ─── Business Type Content ────────────────────────────────────────────────────

BUSINESS_SUMMARIES = {
    "restaurant": {
        "pain_points": [
            "Missed phone orders during rush hours",
            "No-show reservations costing empty tables",
            "Outdated online presence losing customers to competitors",
            "No way to track repeat customers or send promotions",
        ],
        "value_prop": "We help restaurants fill more seats, take more orders, and turn first-time visitors into regulars — all through smart automation that works while you cook.",
        "industry_stat": "73% of diners check a restaurant's website before visiting. 60% of calls to restaurants go unanswered during peak hours.",
    },
    "barbershop": {
        "pain_points": [
            "Walk-in chaos with no appointment management",
            "Phone ringing non-stop during busy cuts",
            "No way to notify clients about openings or cancellations",
            "Losing clients to shops with better online booking",
        ],
        "value_prop": "We help barbershops fill every chair, eliminate phone interruptions, and build a loyal client base that books on repeat — so you can focus on the craft.",
        "industry_stat": "Barbershops with online booking see 30% more appointments. 45% of clients prefer booking outside business hours.",
    },
    "dental": {
        "pain_points": [
            "Front desk overwhelmed with scheduling calls",
            "Patient no-shows costing thousands per month",
            "Outdated website not converting new patients",
            "No automated recall system for cleanings and checkups",
        ],
        "value_prop": "We help dental practices reduce no-shows, fill cancellation gaps instantly, and convert website visitors into booked patients — without adding front desk staff.",
        "industry_stat": "Dental practices lose an average of $150,000/year to no-shows. Automated reminders reduce no-shows by 38%.",
    },
    "auto": {
        "pain_points": [
            "Service advisors tied up on phone instead of with customers",
            "No automated follow-up for maintenance reminders",
            "Online reviews suffering from poor communication",
            "Appointment scheduling still done on paper or whiteboards",
        ],
        "value_prop": "We help auto shops keep bays full, automate service reminders, and deliver the kind of customer communication that earns 5-star reviews — on autopilot.",
        "industry_stat": "Auto repair shops with digital scheduling see 25% higher bay utilization. 67% of customers prefer text updates over phone calls.",
    },
    "realestate": {
        "pain_points": [
            "Missing hot leads because you were showing a property",
            "No instant follow-up on website inquiries",
            "Manual CRM updates eating into selling time",
            "Inconsistent communication across the team",
        ],
        "value_prop": "We help real estate teams capture every lead instantly, automate follow-up sequences, and give agents back hours of their week — so they can focus on closing deals.",
        "industry_stat": "78% of buyers go with the agent who responds first. Leads contacted within 5 minutes are 9x more likely to convert.",
    },
    "other": {
        "pain_points": [
            "Missed calls and inquiries outside business hours",
            "No centralized customer database",
            "Online presence not generating enough leads",
            "Manual processes eating into productive time",
        ],
        "value_prop": "We help businesses automate their customer-facing operations — from answering the phone to managing appointments to building an online presence that actually converts.",
        "industry_stat": "Small businesses using automation save an average of 10 hours per week. 85% of customers expect instant responses to inquiries.",
    },
}

# ─── Case Studies ─────────────────────────────────────────────────────────────

CASE_STUDIES = {
    "delhi_palace": {
        "name": "Delhi Palace",
        "type": "restaurant",
        "location": "Flagstaff, AZ",
        "summary": "Full digital transformation for an Indian restaurant relocating to a new address.",
        "results": [
            "Custom website with 92-item interactive menu and online ordering",
            "Kitchen Display System (KDS) for real-time order management",
            "SEO-optimized pages ranking on first page for 'Indian food Flagstaff'",
            "Google Maps integration with correct new-location coordinates",
            "Mobile-responsive design with 90+ Lighthouse performance score",
        ],
        "quote": "OpenClaw built us a complete digital presence in under a week. Our online orders doubled in the first month.",
    },
    "surgeon_cuts": {
        "name": "Surgeon Cuts Barbershop",
        "type": "barbershop",
        "location": "Flagstaff, AZ",
        "summary": "AI receptionist and full CRM system for a busy 4-chair barbershop.",
        "results": [
            "AI Receptionist handling 100+ calls/week with natural conversation",
            "Custom CRM tracking 500+ client profiles and appointment history",
            "Online booking reducing phone interruptions by 60%",
            "Automated SMS reminders cutting no-shows by 40%",
            "Real-time analytics dashboard for revenue and barber performance",
        ],
        "quote": "The AI receptionist handles our phones so my barbers can focus on cutting. It paid for itself in the first week.",
    },
}

# Map business types to relevant case studies
CASE_STUDY_MAP = {
    "restaurant": ["delhi_palace"],
    "barbershop": ["surgeon_cuts"],
    "dental": ["delhi_palace", "surgeon_cuts"],
    "auto": ["surgeon_cuts"],
    "realestate": ["delhi_palace", "surgeon_cuts"],
    "other": ["delhi_palace", "surgeon_cuts"],
    "full_package": ["delhi_palace", "surgeon_cuts"],
}


# ─── Slug Utility ─────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


# ─── HTML Generator ───────────────────────────────────────────────────────────

def _generate_proposal_html(
    business_name: str,
    business_type: str,
    owner_name: str,
    selected_services: list,
    custom_notes: str = "",
) -> str:
    """Generate a complete branded HTML proposal document."""

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %d, %Y")
    proposal_id = f"OC-{now.strftime('%Y%m%d')}-{_slugify(business_name)[:12].upper()}"

    biz = BUSINESS_SUMMARIES.get(business_type, BUSINESS_SUMMARIES["other"])

    # Determine if full_package is selected — if so, use its pricing
    is_full = "full_package" in selected_services
    if is_full:
        services_to_show = ["full_package"]
    else:
        services_to_show = [s for s in selected_services if s in SERVICE_CATALOG]

    if not services_to_show:
        services_to_show = ["website"]  # fallback

    # Calculate totals
    total_setup = sum(SERVICE_CATALOG[s]["price"] for s in services_to_show)
    total_monthly = sum(SERVICE_CATALOG[s]["monthly"] for s in services_to_show)
    max_timeline = max(SERVICE_CATALOG[s]["timeline_days"] for s in services_to_show)
    timeline_str = f"{max_timeline} business days" if len(services_to_show) == 1 else f"{max_timeline} business days"

    # Determine which case studies to show
    case_study_keys = set()
    if is_full:
        case_study_keys = {"delhi_palace", "surgeon_cuts"}
    else:
        for s in services_to_show:
            for key in CASE_STUDY_MAP.get(business_type, ["delhi_palace", "surgeon_cuts"]):
                case_study_keys.add(key)

    # Build services HTML
    services_html = ""
    for svc_key in services_to_show:
        svc = SERVICE_CATALOG[svc_key]
        scope_items = "\n".join(f'<li>{item}</li>' for item in svc["scope"])
        deliverable_items = "\n".join(f'<li>{item}</li>' for item in svc["deliverables"])
        services_html += f"""
        <div class="service-card">
            <div class="service-header">
                <h3>{svc["name"]}</h3>
                <span class="service-tagline">{svc["tagline"]}</span>
            </div>
            <div class="service-body">
                <div class="service-section">
                    <h4>Scope</h4>
                    <ul>{scope_items}</ul>
                </div>
                <div class="service-section">
                    <h4>Deliverables</h4>
                    <ul>{deliverable_items}</ul>
                </div>
            </div>
        </div>
        """

    # Build pricing table rows
    pricing_rows = ""
    for svc_key in services_to_show:
        svc = SERVICE_CATALOG[svc_key]
        pricing_rows += f"""
        <tr>
            <td>{svc["name"]}</td>
            <td class="price">${svc["price"]:,}</td>
            <td class="price">${svc["monthly"]:,}/mo</td>
        </tr>
        """

    # Build case studies HTML
    case_studies_html = ""
    for cs_key in case_study_keys:
        cs = CASE_STUDIES[cs_key]
        results_items = "\n".join(f'<li>{r}</li>' for r in cs["results"])
        case_studies_html += f"""
        <div class="case-study">
            <div class="case-study-header">
                <h3>{cs["name"]}</h3>
                <span class="case-study-meta">{cs["type"].title()} &bull; {cs["location"]}</span>
            </div>
            <p class="case-study-summary">{cs["summary"]}</p>
            <ul class="case-study-results">{results_items}</ul>
            <blockquote class="testimonial">&ldquo;{cs["quote"]}&rdquo;</blockquote>
        </div>
        """

    # Pain points
    pain_points_html = "\n".join(f'<li>{p}</li>' for p in biz["pain_points"])

    # Custom notes section
    custom_notes_html = ""
    if custom_notes and custom_notes.strip():
        custom_notes_html = f"""
        <section class="section notes-section">
            <h2>Additional Notes</h2>
            <div class="notes-content">
                <p>{custom_notes}</p>
            </div>
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenClaw Proposal &mdash; {business_name}</title>
    <style>
        /* ─── Reset & Base ─────────────────────────────────────────── */
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        :root {{
            --brand-dark: #0f172a;
            --brand-primary: #6366f1;
            --brand-primary-light: #818cf8;
            --brand-accent: #22d3ee;
            --brand-success: #10b981;
            --brand-warning: #f59e0b;
            --gray-50: #f8fafc;
            --gray-100: #f1f5f9;
            --gray-200: #e2e8f0;
            --gray-300: #cbd5e1;
            --gray-500: #64748b;
            --gray-700: #334155;
            --gray-800: #1e293b;
            --gray-900: #0f172a;
            --radius: 12px;
            --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
            --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
            --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1);
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            color: var(--gray-800);
            background: var(--gray-50);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }}

        /* ─── Header ───────────────────────────────────────────────── */
        .header {{
            background: linear-gradient(135deg, var(--brand-dark) 0%, #1e1b4b 50%, var(--brand-dark) 100%);
            color: white;
            padding: 60px 40px;
            position: relative;
            overflow: hidden;
        }}

        .header::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -20%;
            width: 600px;
            height: 600px;
            background: radial-gradient(circle, rgba(99,102,241,0.15) 0%, transparent 70%);
            border-radius: 50%;
        }}

        .header::after {{
            content: '';
            position: absolute;
            bottom: -30%;
            left: -10%;
            width: 400px;
            height: 400px;
            background: radial-gradient(circle, rgba(34,211,238,0.1) 0%, transparent 70%);
            border-radius: 50%;
        }}

        .header-content {{
            max-width: 900px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }}

        .logo {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 40px;
        }}

        .logo-icon {{
            width: 48px;
            height: 48px;
            background: linear-gradient(135deg, var(--brand-primary), var(--brand-accent));
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: 800;
            color: white;
        }}

        .logo-text {{
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}

        .header h1 {{
            font-size: 42px;
            font-weight: 800;
            line-height: 1.1;
            margin-bottom: 8px;
            letter-spacing: -1px;
        }}

        .header .subtitle {{
            font-size: 20px;
            color: var(--brand-primary-light);
            font-weight: 500;
        }}

        .header .meta {{
            margin-top: 24px;
            display: flex;
            gap: 32px;
            font-size: 14px;
            color: var(--gray-300);
        }}

        .header .meta span {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        /* ─── Container ────────────────────────────────────────────── */
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 0 40px;
        }}

        /* ─── Sections ─────────────────────────────────────────────── */
        .section {{
            padding: 48px 0;
            border-bottom: 1px solid var(--gray-200);
        }}

        .section:last-child {{
            border-bottom: none;
        }}

        .section h2 {{
            font-size: 28px;
            font-weight: 700;
            color: var(--gray-900);
            margin-bottom: 24px;
            letter-spacing: -0.5px;
        }}

        .section h2::after {{
            content: '';
            display: block;
            width: 48px;
            height: 4px;
            background: linear-gradient(90deg, var(--brand-primary), var(--brand-accent));
            border-radius: 2px;
            margin-top: 8px;
        }}

        /* ─── Executive Summary ────────────────────────────────────── */
        .exec-summary {{
            background: white;
            border-radius: var(--radius);
            padding: 32px;
            box-shadow: var(--shadow-md);
        }}

        .exec-summary .value-prop {{
            font-size: 18px;
            color: var(--gray-700);
            line-height: 1.7;
            margin-bottom: 24px;
            border-left: 4px solid var(--brand-primary);
            padding-left: 20px;
        }}

        .pain-points {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 24px;
        }}

        .pain-points li {{
            list-style: none;
            padding: 12px 16px;
            background: #fef2f2;
            border-radius: 8px;
            font-size: 14px;
            color: #991b1b;
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }}

        .pain-points li::before {{
            content: '\\2717';
            font-weight: 700;
            color: #dc2626;
            flex-shrink: 0;
            margin-top: 1px;
        }}

        .industry-stat {{
            background: var(--gray-100);
            padding: 16px 20px;
            border-radius: 8px;
            font-size: 14px;
            color: var(--gray-500);
            font-style: italic;
        }}

        /* ─── Service Cards ────────────────────────────────────────── */
        .service-card {{
            background: white;
            border-radius: var(--radius);
            box-shadow: var(--shadow-md);
            overflow: hidden;
            margin-bottom: 24px;
            border: 1px solid var(--gray-200);
            transition: box-shadow 0.2s;
        }}

        .service-card:hover {{
            box-shadow: var(--shadow-lg);
        }}

        .service-header {{
            background: linear-gradient(135deg, var(--brand-dark), #1e1b4b);
            color: white;
            padding: 24px 28px;
        }}

        .service-header h3 {{
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 4px;
        }}

        .service-tagline {{
            font-size: 14px;
            color: var(--brand-accent);
            font-weight: 500;
        }}

        .service-body {{
            padding: 28px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 28px;
        }}

        .service-section h4 {{
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--brand-primary);
            margin-bottom: 12px;
        }}

        .service-section ul {{
            list-style: none;
        }}

        .service-section li {{
            padding: 6px 0;
            font-size: 14px;
            color: var(--gray-700);
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }}

        .service-section li::before {{
            content: '\\2713';
            color: var(--brand-success);
            font-weight: 700;
            flex-shrink: 0;
            margin-top: 1px;
        }}

        /* ─── Pricing Table ────────────────────────────────────────── */
        .pricing-table {{
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: var(--radius);
            overflow: hidden;
            box-shadow: var(--shadow-md);
        }}

        .pricing-table thead {{
            background: var(--brand-dark);
            color: white;
        }}

        .pricing-table th {{
            padding: 16px 24px;
            text-align: left;
            font-size: 14px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .pricing-table td {{
            padding: 16px 24px;
            border-bottom: 1px solid var(--gray-100);
            font-size: 15px;
        }}

        .pricing-table .price {{
            font-weight: 700;
            color: var(--brand-primary);
            font-variant-numeric: tabular-nums;
        }}

        .pricing-table tfoot {{
            background: var(--gray-50);
            font-weight: 700;
        }}

        .pricing-table tfoot td {{
            border-bottom: none;
            font-size: 16px;
        }}

        .pricing-note {{
            margin-top: 16px;
            font-size: 13px;
            color: var(--gray-500);
        }}

        /* ─── Case Studies ─────────────────────────────────────────── */
        .case-study {{
            background: white;
            border-radius: var(--radius);
            padding: 28px;
            box-shadow: var(--shadow-md);
            margin-bottom: 24px;
            border: 1px solid var(--gray-200);
        }}

        .case-study-header {{
            display: flex;
            align-items: baseline;
            gap: 16px;
            margin-bottom: 12px;
        }}

        .case-study-header h3 {{
            font-size: 20px;
            font-weight: 700;
            color: var(--gray-900);
        }}

        .case-study-meta {{
            font-size: 13px;
            color: var(--gray-500);
        }}

        .case-study-summary {{
            font-size: 15px;
            color: var(--gray-700);
            margin-bottom: 16px;
        }}

        .case-study-results {{
            list-style: none;
            margin-bottom: 16px;
        }}

        .case-study-results li {{
            padding: 6px 0;
            font-size: 14px;
            color: var(--gray-700);
            display: flex;
            align-items: flex-start;
            gap: 8px;
        }}

        .case-study-results li::before {{
            content: '\\2713';
            color: var(--brand-success);
            font-weight: 700;
            flex-shrink: 0;
        }}

        .testimonial {{
            border-left: 4px solid var(--brand-primary);
            padding: 16px 20px;
            background: var(--gray-50);
            border-radius: 0 8px 8px 0;
            font-style: italic;
            color: var(--gray-700);
            font-size: 15px;
        }}

        /* ─── Timeline ─────────────────────────────────────────────── */
        .timeline-bar {{
            display: flex;
            gap: 0;
            margin: 24px 0;
        }}

        .timeline-step {{
            flex: 1;
            text-align: center;
            position: relative;
        }}

        .timeline-step::before {{
            content: '';
            display: block;
            height: 6px;
            background: var(--brand-primary);
            opacity: 0.2;
            border-radius: 3px;
            margin-bottom: 16px;
        }}

        .timeline-step.active::before {{
            opacity: 1;
            background: linear-gradient(90deg, var(--brand-primary), var(--brand-accent));
        }}

        .timeline-step .step-num {{
            display: inline-flex;
            width: 32px;
            height: 32px;
            align-items: center;
            justify-content: center;
            background: var(--brand-primary);
            color: white;
            border-radius: 50%;
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .timeline-step h4 {{
            font-size: 14px;
            font-weight: 600;
            color: var(--gray-900);
            margin-bottom: 4px;
        }}

        .timeline-step p {{
            font-size: 12px;
            color: var(--gray-500);
        }}

        /* ─── Terms ────────────────────────────────────────────────── */
        .terms-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}

        .term-card {{
            background: white;
            border-radius: var(--radius);
            padding: 24px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--gray-200);
        }}

        .term-card h4 {{
            font-size: 14px;
            font-weight: 700;
            color: var(--brand-primary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}

        .term-card p {{
            font-size: 14px;
            color: var(--gray-700);
            line-height: 1.6;
        }}

        /* ─── Notes Section ────────────────────────────────────────── */
        .notes-content {{
            background: #fffbeb;
            border: 1px solid #fde68a;
            border-radius: var(--radius);
            padding: 24px;
            font-size: 15px;
            color: #92400e;
            line-height: 1.7;
        }}

        /* ─── Footer ───────────────────────────────────────────────── */
        .footer {{
            background: var(--brand-dark);
            color: white;
            padding: 48px 40px;
            margin-top: 48px;
        }}

        .footer-content {{
            max-width: 900px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}

        .footer-brand h3 {{
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .footer-brand p {{
            font-size: 14px;
            color: var(--gray-300);
            line-height: 1.6;
        }}

        .footer-contact {{
            text-align: right;
        }}

        .footer-contact p {{
            font-size: 14px;
            color: var(--gray-300);
            margin-bottom: 4px;
        }}

        .footer-contact a {{
            color: var(--brand-accent);
            text-decoration: none;
        }}

        .footer-cta {{
            margin-top: 32px;
            text-align: center;
            padding-top: 32px;
            border-top: 1px solid rgba(255,255,255,0.1);
        }}

        .footer-cta p {{
            font-size: 16px;
            color: var(--gray-300);
        }}

        .footer-cta .cta-button {{
            display: inline-block;
            margin-top: 16px;
            padding: 14px 36px;
            background: linear-gradient(135deg, var(--brand-primary), var(--brand-primary-light));
            color: white;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            text-decoration: none;
            transition: opacity 0.2s;
        }}

        .footer-cta .cta-button:hover {{
            opacity: 0.9;
        }}

        /* ─── Print ────────────────────────────────────────────────── */
        @media print {{
            body {{ background: white; }}
            .header {{ break-after: avoid; }}
            .section {{ break-inside: avoid; }}
            .service-card {{ break-inside: avoid; }}
            .case-study {{ break-inside: avoid; }}
        }}

        @media (max-width: 768px) {{
            .header {{ padding: 40px 24px; }}
            .header h1 {{ font-size: 28px; }}
            .header .meta {{ flex-direction: column; gap: 8px; }}
            .container {{ padding: 0 24px; }}
            .pain-points {{ grid-template-columns: 1fr; }}
            .service-body {{ grid-template-columns: 1fr; }}
            .terms-grid {{ grid-template-columns: 1fr; }}
            .footer-content {{ flex-direction: column; gap: 24px; }}
            .footer-contact {{ text-align: left; }}
        }}
    </style>
</head>
<body>

    <!-- ─── Header ─────────────────────────────────────────────── -->
    <div class="header">
        <div class="header-content">
            <div class="logo">
                <div class="logo-icon">OC</div>
                <span class="logo-text">OpenClaw</span>
            </div>
            <h1>Prepared for {business_name}</h1>
            <div class="subtitle">AI-Powered Business Solutions Proposal</div>
            <div class="meta">
                <span>Proposal #{proposal_id}</span>
                <span>{date_str}</span>
                <span>Prepared for {owner_name}</span>
            </div>
        </div>
    </div>

    <div class="container">

        <!-- ─── Executive Summary ──────────────────────────────── -->
        <section class="section">
            <h2>Executive Summary</h2>
            <div class="exec-summary">
                <p class="value-prop">{biz["value_prop"]}</p>

                <h4 style="font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:var(--gray-500); margin-bottom:12px;">
                    Challenges We Will Solve
                </h4>
                <ul class="pain-points">
                    {pain_points_html}
                </ul>

                <div class="industry-stat">{biz["industry_stat"]}</div>
            </div>
        </section>

        <!-- ─── Selected Services ──────────────────────────────── -->
        <section class="section">
            <h2>Selected Services</h2>
            {services_html}
        </section>

        <!-- ─── Pricing ────────────────────────────────────────── -->
        <section class="section">
            <h2>Investment</h2>
            <table class="pricing-table">
                <thead>
                    <tr>
                        <th>Service</th>
                        <th>Setup Fee</th>
                        <th>Monthly</th>
                    </tr>
                </thead>
                <tbody>
                    {pricing_rows}
                </tbody>
                <tfoot>
                    <tr>
                        <td>Total</td>
                        <td class="price">${total_setup:,}</td>
                        <td class="price">${total_monthly:,}/mo</td>
                    </tr>
                </tfoot>
            </table>
            <p class="pricing-note">
                Monthly fees begin after project delivery. No long-term contracts &mdash; cancel anytime with 30 days notice.
            </p>
        </section>

        <!-- ─── Case Studies ───────────────────────────────────── -->
        <section class="section">
            <h2>Proven Results</h2>
            {case_studies_html}
        </section>

        <!-- ─── Timeline ───────────────────────────────────────── -->
        <section class="section">
            <h2>Timeline</h2>
            <p style="color:var(--gray-700); margin-bottom:24px;">
                Estimated delivery: <strong>{timeline_str}</strong> from project kickoff.
            </p>
            <div class="timeline-bar">
                <div class="timeline-step active">
                    <div class="step-num">1</div>
                    <h4>Discovery</h4>
                    <p>Day 1</p>
                </div>
                <div class="timeline-step active">
                    <div class="step-num">2</div>
                    <h4>Build</h4>
                    <p>Days 2&ndash;{max(2, max_timeline - 2)}</p>
                </div>
                <div class="timeline-step active">
                    <div class="step-num">3</div>
                    <h4>Review</h4>
                    <p>Day {max(3, max_timeline - 1)}</p>
                </div>
                <div class="timeline-step active">
                    <div class="step-num">4</div>
                    <h4>Launch</h4>
                    <p>Day {max_timeline}</p>
                </div>
            </div>
        </section>

        <!-- ─── Terms ──────────────────────────────────────────── -->
        <section class="section">
            <h2>Terms</h2>
            <div class="terms-grid">
                <div class="term-card">
                    <h4>Payment Schedule</h4>
                    <p>50% upfront to begin work (${total_setup // 2:,}). Remaining 50% due on project completion and approval (${total_setup - total_setup // 2:,}).</p>
                </div>
                <div class="term-card">
                    <h4>Monthly Services</h4>
                    <p>${total_monthly:,}/month begins after go-live. Includes hosting, maintenance, AI usage, and support. Cancel anytime with 30 days notice.</p>
                </div>
                <div class="term-card">
                    <h4>Revisions</h4>
                    <p>Up to 3 rounds of revisions included. Additional revision rounds billed at $75/hour.</p>
                </div>
                <div class="term-card">
                    <h4>Ownership</h4>
                    <p>You own 100% of the final product. All code, designs, and content are transferred to you upon final payment.</p>
                </div>
            </div>
        </section>

        {custom_notes_html}

    </div>

    <!-- ─── Footer ─────────────────────────────────────────────── -->
    <div class="footer">
        <div class="footer-content">
            <div class="footer-brand">
                <h3>OpenClaw</h3>
                <p>AI-Powered Business Solutions<br>Flagstaff, Arizona</p>
            </div>
            <div class="footer-contact">
                <p><your-domain></p>
                <p>Flagstaff, AZ 86001</p>
            </div>
        </div>
        <div class="footer-cta">
            <p>Ready to get started?</p>
            <a href="mailto:miles@<your-domain>" class="cta-button">Accept This Proposal</a>
        </div>
    </div>

</body>
</html>"""

    return html


# ─── Main Tool Function ──────────────────────────────────────────────────────

def generate_proposal(
    business_name: str,
    business_type: str,
    owner_name: str,
    selected_services: list,
    custom_notes: str = "",
) -> str:
    """
    Generate a branded client proposal and save it to disk.

    Returns JSON string with: proposal_id, file_path, total_setup, total_monthly,
    timeline, services, and the full HTML content.
    """
    # Validate inputs
    if not business_name or not business_name.strip():
        return json.dumps({"error": "business_name is required"})

    business_type = business_type.lower().strip() if business_type else "other"
    if business_type not in VALID_BUSINESS_TYPES:
        business_type = "other"

    if not owner_name or not owner_name.strip():
        owner_name = "Business Owner"

    if not selected_services or not isinstance(selected_services, list):
        return json.dumps({"error": "selected_services must be a non-empty list. Valid: receptionist, website, crm, full_package"})

    # Filter to valid services
    valid_selected = [s for s in selected_services if s in VALID_SERVICES]
    if not valid_selected:
        return json.dumps({"error": f"No valid services selected. Choose from: {', '.join(VALID_SERVICES)}"})

    try:
        # Generate HTML
        html = _generate_proposal_html(
            business_name=business_name.strip(),
            business_type=business_type,
            owner_name=owner_name.strip(),
            selected_services=valid_selected,
            custom_notes=custom_notes or "",
        )

        # Save to disk
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        slug = _slugify(business_name)
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        filename = f"{slug}_{timestamp}.html"
        filepath = DATA_DIR / filename
        filepath.write_text(html, encoding="utf-8")

        # Determine totals for response
        is_full = "full_package" in valid_selected
        services_to_price = ["full_package"] if is_full else valid_selected
        total_setup = sum(SERVICE_CATALOG[s]["price"] for s in services_to_price)
        total_monthly = sum(SERVICE_CATALOG[s]["monthly"] for s in services_to_price)
        max_timeline = max(SERVICE_CATALOG[s]["timeline_days"] for s in services_to_price)

        proposal_id = f"OC-{now.strftime('%Y%m%d')}-{slug[:12].upper()}"

        # Log to index
        index_entry = {
            "proposal_id": proposal_id,
            "business_name": business_name.strip(),
            "business_type": business_type,
            "owner_name": owner_name.strip(),
            "services": valid_selected,
            "total_setup": total_setup,
            "total_monthly": total_monthly,
            "timeline_days": max_timeline,
            "file": filename,
            "created_at": now.isoformat(),
        }
        with open(INDEX_PATH, "a") as f:
            f.write(json.dumps(index_entry) + "\n")

        return json.dumps({
            "status": "success",
            "proposal_id": proposal_id,
            "file_path": str(filepath),
            "business_name": business_name.strip(),
            "owner_name": owner_name.strip(),
            "business_type": business_type,
            "services": valid_selected,
            "total_setup": total_setup,
            "total_monthly": total_monthly,
            "timeline_days": max_timeline,
            "html_length": len(html),
            "message": f"Proposal saved to {filepath}",
        })

    except Exception as e:
        logger.error(f"Proposal generation error: {e}", exc_info=True)
        return json.dumps({"error": str(e)})
