"""HTML email generation for job alerts.

This module creates nicely styled HTML emails with:
- CSS carousel with radio/:checked for Apple Mail/iOS
- Horizontal scroll fallback for Gmail
- Panda hero image visible in all clients (background + <img> fallback)
- Pay range and application question badges from real ATS data
"""
import html
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .direct_links import get_direct_link, DirectLink

LOG = logging.getLogger(__name__)

PANDA_IMAGE_PATH = Path(__file__).parent.parent / "assets" / "panda-hero.jpg"
PANDA_GITHUB_URL = "https://raw.githubusercontent.com/kriscCodes/bubu-jobs/cursor/resolve-ats-urls-56c4/assets/panda-hero.jpg"


@dataclass
class JobCard:
    """Data for a single job card in the email."""
    company: str
    title: str
    location: str
    date: str
    apply_url: str
    is_direct_link: bool
    source_note: str = ""
    work_model: str = ""
    ats: str = ""
    pay_range: str = ""
    has_written_questions: Optional[bool] = None
    pay_source: str = ""
    questions_source: str = ""


COLORS = {
    "primary": "#6366f1",
    "primary_dark": "#4f46e5",
    "primary_light": "#e0e7ff",
    "success": "#10b981",
    "success_light": "#d1fae5",
    "warning": "#f59e0b",
    "warning_light": "#fef3c7",
    "info": "#3b82f6",
    "info_light": "#dbeafe",
    "gray_50": "#f9fafb",
    "gray_100": "#f3f4f6",
    "gray_200": "#e5e7eb",
    "gray_300": "#d1d5db",
    "gray_500": "#6b7280",
    "gray_700": "#374151",
    "gray_900": "#111827",
    "white": "#ffffff",
    "pink_50": "#fdf2f8",
    "pink_100": "#fce7f3",
    "bg_fallback": "#e8d5f0",
}


def _escape(text: str) -> str:
    """HTML escape text."""
    return html.escape(str(text))


def _get_question_indicator(has_written_questions: Optional[bool]) -> tuple[str, str, str]:
    """Return (icon, label, bg_color) for question indicator."""
    if has_written_questions is True:
        return ("✍️", "Written response", COLORS["warning_light"])
    elif has_written_questions is False:
        return ("⚡", "Quick apply", COLORS["success_light"])
    else:
        return ("❓", "Unknown", COLORS["gray_200"])


def _render_carousel_card(job: JobCard, index: int, total: int) -> str:
    """Render a single card for the carousel."""
    badge_text = "Direct" if job.is_direct_link else "Jobright"
    badge_bg = COLORS["success_light"] if job.is_direct_link else COLORS["warning_light"]
    badge_color = COLORS["success"] if job.is_direct_link else COLORS["warning"]
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_indicator(job.has_written_questions)
    
    return f'''<div class="slide slide-{index}" style="flex: 0 0 auto; width: 260px; background-color: {COLORS['white']}; border: 1px solid {COLORS['gray_200']}; border-radius: 12px; padding: 16px; margin-right: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
                <td><span style="font-size: 11px; color: {COLORS['gray_500']}; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">{_escape(job.company)}</span></td>
                <td style="text-align: right;"><span style="display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 9px; font-weight: 600; background-color: {badge_bg}; color: {badge_color}; text-transform: uppercase;">{badge_text}</span></td>
            </tr>
        </table>
        <h3 style="font-size: 14px; font-weight: 700; color: {COLORS['gray_900']}; margin: 8px 0 6px 0; line-height: 1.3; height: 36px; overflow: hidden;">{_escape(job.title)}</h3>
        <p style="font-size: 12px; color: {COLORS['gray_500']}; margin: 0 0 4px 0;">📍 {_escape(job.location)}</p>
        <p style="font-size: 12px; font-weight: 600; color: {COLORS['primary']}; margin: 0 0 8px 0;">💰 {_escape(pay_display)}</p>
        <span style="display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; background-color: {q_bg}; color: {COLORS['gray_700']};">{q_icon} {q_label}</span>
        <div style="margin-top: 12px;">
            <a href="{_escape(job.apply_url)}" style="display: block; background-color: {COLORS['primary']}; color: {COLORS['white']}; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; text-align: center;">Apply →</a>
        </div>
        <p style="font-size: 10px; color: {COLORS['gray_300']}; margin: 8px 0 0 0; text-align: center;">{index + 1} of {total}</p>
    </div>'''


def _render_stacked_card(job: JobCard) -> str:
    """Render a single card for stacked layout (mobile/fallback)."""
    badge_text = "Direct" if job.is_direct_link else "Jobright"
    badge_bg = COLORS["success_light"] if job.is_direct_link else COLORS["warning_light"]
    badge_color = COLORS["success"] if job.is_direct_link else COLORS["warning"]
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_indicator(job.has_written_questions)
    
    return f'''<tr>
        <td style="padding: 8px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border: 1px solid {COLORS['gray_200']}; border-radius: 12px;">
                <tr>
                    <td style="padding: 14px;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td><span style="font-size: 11px; color: {COLORS['gray_500']}; text-transform: uppercase; font-weight: 600;">{_escape(job.company)}</span></td>
                                <td style="text-align: right;"><span style="display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 9px; font-weight: 600; background-color: {badge_bg}; color: {badge_color}; text-transform: uppercase;">{badge_text}</span></td>
                            </tr>
                        </table>
                        <h3 style="font-size: 14px; font-weight: 700; color: {COLORS['gray_900']}; margin: 6px 0; line-height: 1.3;">{_escape(job.title)}</h3>
                        <p style="font-size: 12px; color: {COLORS['gray_500']}; margin: 0 0 3px 0;">📍 {_escape(job.location)}</p>
                        <p style="font-size: 12px; font-weight: 600; color: {COLORS['primary']}; margin: 0 0 8px 0;">💰 {_escape(pay_display)}</p>
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td><span style="display: inline-block; padding: 3px 8px; border-radius: 6px; font-size: 10px; background-color: {q_bg}; color: {COLORS['gray_700']};">{q_icon} {q_label}</span></td>
                                <td style="text-align: right;"><a href="{_escape(job.apply_url)}" style="display: inline-block; background-color: {COLORS['primary']}; color: {COLORS['white']}; text-decoration: none; padding: 8px 14px; border-radius: 6px; font-size: 12px; font-weight: 600;">Apply →</a></td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>'''


def render_html_email(jobs: list[JobCard], subject: str = "New PM Jobs", simulate_gmail: bool = False) -> str:
    """Render a complete HTML email with CSS carousel and Gmail fallbacks.
    
    Features:
    - CSS radio/:checked carousel for Apple Mail/iOS with prev/next controls
    - Horizontal scroll-snap fallback for Gmail
    - Panda hero as both background-image AND <img> for maximum compatibility
    - VML background for Outlook
    """
    timestamp = datetime.now().strftime("%B %d, %Y")
    direct_count = sum(1 for j in jobs if j.is_direct_link)
    jobright_count = len(jobs) - direct_count
    num_jobs = len(jobs)
    
    # Generate carousel cards
    carousel_cards = "\n".join(_render_carousel_card(job, i, num_jobs) for i, job in enumerate(jobs))
    
    # Generate stacked cards for mobile/fallback
    stacked_cards = "\n".join(_render_stacked_card(job) for job in jobs)
    
    # Generate radio inputs for carousel
    radio_inputs = "\n".join(
        f'<input type="radio" name="c" id="s{i}" class="carousel-radio" style="display:none!important;position:absolute;opacity:0;" {"checked" if i == 0 else ""}>'
        for i in range(num_jobs)
    )
    
    # Generate CSS rules for showing slides based on checked radio
    slide_visibility_css = "\n".join(
        f"#s{i}:checked ~ .carousel-container .slide-{i} {{ outline: 3px solid {COLORS['primary']}; }}"
        for i in range(num_jobs)
    )
    
    # Generate prev/next navigation labels
    nav_labels = []
    for i in range(num_jobs):
        prev_i = (i - 1) % num_jobs
        next_i = (i + 1) % num_jobs
        nav_labels.append(f'''<span class="nav nav-{i}" style="display:none;">
            <label for="s{prev_i}" style="display:inline-block;padding:6px 14px;background:{COLORS['gray_100']};border-radius:6px;cursor:pointer;font-size:13px;margin-right:8px;">← Prev</label>
            <label for="s{next_i}" style="display:inline-block;padding:6px 14px;background:{COLORS['primary']};color:white;border-radius:6px;cursor:pointer;font-size:13px;">Next →</label>
        </span>''')
    nav_html = "\n".join(nav_labels)
    
    # CSS to show correct nav
    nav_visibility_css = "\n".join(f"#s{i}:checked ~ .carousel-nav .nav-{i} {{ display: inline-block !important; }}" for i in range(num_jobs))
    
    panda_url = PANDA_GITHUB_URL
    
    return f'''<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{_escape(subject)}</title>
    <!--[if mso]>
    <noscript><xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
    <style>table {{ border-collapse: collapse; }} td {{ font-family: Arial, sans-serif; }}</style>
    <![endif]-->
    <style type="text/css">
        body, table, td {{ margin: 0; padding: 0; }}
        img {{ border: 0; display: block; }}
        .carousel-radio {{ display: none !important; }}
        
        /* Default: show stacked, hide carousel */
        .carousel-wrapper {{ display: none; }}
        .stacked-wrapper {{ display: block; }}
        
        /* Carousel for clients supporting :checked (Apple Mail, iOS Mail) */
        @supports selector(:checked) {{
            .carousel-wrapper {{ display: block !important; }}
            .stacked-wrapper {{ display: none !important; }}
            
            .carousel-container {{
                display: flex;
                overflow-x: auto;
                scroll-snap-type: x mandatory;
                -webkit-overflow-scrolling: touch;
                padding: 8px 4px;
                margin: 0 -4px;
            }}
            .carousel-container .slide {{
                scroll-snap-align: start;
            }}
            
            {slide_visibility_css}
            {nav_visibility_css}
        }}
        
        /* Mobile */
        @media only screen and (max-width: 560px) {{
            .carousel-wrapper {{ display: none !important; }}
            .stacked-wrapper {{ display: block !important; }}
            .wrapper {{ padding: 12px !important; }}
            .hero-cell {{ padding: 20px 16px !important; }}
        }}
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: {COLORS['bg_fallback']}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;">
    
    <!-- Outer wrapper -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['bg_fallback']};">
        <tr>
            <td align="center" style="padding: 20px 0;">
                
                <!-- Main container 540px -->
                <table role="presentation" width="540" cellpadding="0" cellspacing="0" border="0" class="wrapper" style="max-width: 540px; width: 100%;">
                    
                    <!-- Hero Header with Panda -->
                    <tr>
                        <td>
                            <!--[if gte mso 9]>
                            <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:540px;height:200px;">
                                <v:fill type="frame" src="{panda_url}" color="{COLORS['primary']}" />
                                <v:textbox inset="0,0,0,0" style="mso-fit-shape-to-text:true">
                            <![endif]-->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['primary']}; background-image: url('{panda_url}'); background-repeat: no-repeat; background-position: right top; background-size: 180px auto; border-radius: 16px 16px 0 0;">
                                <tr>
                                    <td class="hero-cell" style="padding: 30px 24px;">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="width: 60%;">
                                                    <h1 style="color: {COLORS['white']}; margin: 0 0 8px 0; font-size: 24px; font-weight: 700; text-shadow: 0 1px 3px rgba(0,0,0,0.3);">🎋 {_escape(subject)}</h1>
                                                    <p style="color: rgba(255,255,255,0.95); margin: 0; font-size: 14px; text-shadow: 0 1px 2px rgba(0,0,0,0.2);">{num_jobs} new posting{"s" if num_jobs != 1 else ""} • {timestamp}</p>
                                                </td>
                                                <td style="width: 40%; text-align: right; vertical-align: top;">
                                                    <!-- Panda image for Gmail (where bg-image may not show) -->
                                                    <img src="{panda_url}" alt="🐼" width="100" height="100" style="width: 100px; height: 100px; border-radius: 50%; opacity: 0.9; border: 3px solid rgba(255,255,255,0.3);">
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            <!--[if gte mso 9]>
                                </v:textbox>
                            </v:rect>
                            <![endif]-->
                        </td>
                    </tr>
                    
                    <!-- Stats Bar -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']};">
                                <tr>
                                    <td style="padding: 12px 24px; border-bottom: 1px solid {COLORS['gray_200']};">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="text-align: center; width: 50%;">
                                                    <span style="display: inline-block; width: 8px; height: 8px; background-color: {COLORS['success']}; border-radius: 50%; vertical-align: middle;"></span>
                                                    <span style="font-size: 13px; color: {COLORS['gray_700']}; margin-left: 6px; vertical-align: middle;">{direct_count} Direct</span>
                                                </td>
                                                <td style="text-align: center; width: 50%;">
                                                    <span style="display: inline-block; width: 8px; height: 8px; background-color: {COLORS['warning']}; border-radius: 50%; vertical-align: middle;"></span>
                                                    <span style="font-size: 13px; color: {COLORS['gray_700']}; margin-left: 6px; vertical-align: middle;">{jobright_count} Jobright</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Content Area -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border-radius: 0 0 16px 16px;">
                                <tr>
                                    <td style="padding: 20px;">
                                        
                                        <!-- Carousel (Apple Mail/iOS) -->
                                        <div class="carousel-wrapper">
                                            {radio_inputs}
                                            
                                            <div class="carousel-container" style="display: flex; overflow-x: auto; scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch; padding: 8px 4px;">
                                                {carousel_cards}
                                            </div>
                                            
                                            <div class="carousel-nav" style="text-align: center; margin-top: 12px;">
                                                {nav_html}
                                            </div>
                                            
                                            <p style="text-align: center; font-size: 11px; color: {COLORS['gray_500']}; margin: 12px 0 0 0;">← Swipe or click arrows to browse →</p>
                                        </div>
                                        
                                        <!-- Stacked Cards (Gmail/Mobile fallback) -->
                                        <div class="stacked-wrapper">
                                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                                {stacked_cards}
                                            </table>
                                        </div>
                                        
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 20px; text-align: center;">
                            <p style="font-size: 12px; color: {COLORS['gray_500']}; margin: 0 0 6px 0;">Sent with 🐼 by Bubu Jobs</p>
                            <p style="font-size: 11px; color: {COLORS['gray_300']}; margin: 0;">
                                <a href="#" style="color: {COLORS['primary']}; text-decoration: none;">Unsubscribe</a> • 
                                <a href="#" style="color: {COLORS['primary']}; text-decoration: none;">Preferences</a>
                            </p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''


def render_plain_text_email(jobs: list[JobCard], subject: str = "New PM Jobs") -> str:
    """Render a plain text alternative for the email."""
    lines = [
        f"🐼 {subject}",
        "=" * (len(subject) + 3),
        "",
        f"Found {len(jobs)} new product management jobs!",
        "",
    ]
    
    for i, job in enumerate(jobs, 1):
        link_type = "Direct" if job.is_direct_link else "Jobright"
        pay_display = job.pay_range if job.pay_range else "Pay not listed"
        
        if job.has_written_questions is True:
            q_status = "Written response required"
        elif job.has_written_questions is False:
            q_status = "Quick apply"
        else:
            q_status = "Questions: Unknown"
        
        lines.extend([
            f"{i}. {job.company} - {job.title}",
            f"   Location: {job.location}",
            f"   Pay: {pay_display}",
            f"   {q_status}",
        ])
        if job.work_model:
            lines.append(f"   Work model: {job.work_model}")
        lines.extend([
            f"   Posted: {job.date}",
            f"   Link: {link_type}",
            f"   Apply: {job.apply_url}",
            "",
        ])
    
    lines.extend([
        "---",
        "Sent with 🐼 by Bubu Jobs",
    ])
    
    return "\n".join(lines)


def create_job_cards_from_jobs(jobs: list[dict]) -> list[JobCard]:
    """Convert job dicts to JobCard objects, looking up direct links."""
    cards = []
    
    for job in jobs:
        company = job.get("company", "")
        title = job.get("title", "")
        location = job.get("location", "")
        date = job.get("date", "")
        fallback_url = job.get("source_url", job.get("jobright_url", ""))
        work_model = job.get("work_model", "")
        ats = job.get("ats", "")
        pay_range = job.get("pay_range", "")
        has_written_questions = job.get("has_written_questions")
        
        direct_link = get_direct_link(company, title, location)
        
        if direct_link:
            cards.append(JobCard(
                company=company,
                title=title,
                location=location,
                date=date,
                apply_url=direct_link.direct_url,
                is_direct_link=True,
                source_note=direct_link.note,
                work_model=work_model,
                ats=ats,
                pay_range=pay_range,
                has_written_questions=has_written_questions,
            ))
        else:
            cards.append(JobCard(
                company=company,
                title=title,
                location=location,
                date=date,
                apply_url=fallback_url,
                is_direct_link=False,
                work_model=work_model,
                ats=ats,
                pay_range=pay_range,
                has_written_questions=has_written_questions,
            ))
    
    return cards


def render_sample_email_for_preview(simulate_gmail: bool = False) -> tuple[str, str]:
    """Render a sample email with REAL enriched job data for preview/testing.
    
    Uses actual pay ranges and application question data from ATS API lookups.
    
    Returns:
        Tuple of (html_content, plain_text_content)
    """
    # Sample jobs with REAL data from ATS enrichment
    sample_jobs = [
        JobCard(
            company="Roblox",
            title="Associate Product Manager, Early Career",
            location="San Mateo, CA",
            date="Oct 09",
            apply_url="https://careers.roblox.com/jobs/8143976?gh_jid=8143976",
            is_direct_link=True,
            pay_range="",  # No pay data found in Greenhouse API
            has_written_questions=False,  # Greenhouse API: no text questions
            pay_source="No pay data found",
            questions_source="Greenhouse questions API",
        ),
        JobCard(
            company="Capital One",
            title="Senior Associate, Product Manager - Business Cards",
            location="New York, NY",
            date="Oct 10",
            apply_url="https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/New-York-NY/Senior-Associate--Product-Manager_R1003243-2",
            is_direct_link=True,
            pay_range="$111,200 - $126,900",  # Real data from Workday page
            has_written_questions=None,  # Workday doesn't expose this
            pay_source="Workday job page",
            questions_source="Workday (could not determine)",
        ),
        JobCard(
            company="impact.com",
            title="Associate Product Manager (Contracting)",
            location="Santa Barbara, CA",
            date="Oct 10",
            apply_url="https://job-boards.greenhouse.io/impact/jobs/8871230002",
            is_direct_link=True,
            pay_range="$85,000 - $95,000/year",  # Real data from Greenhouse job content
            has_written_questions=False,  # Greenhouse API: no text questions
            pay_source="Greenhouse job content",
            questions_source="Greenhouse questions API",
        ),
        JobCard(
            company="Arrive Logistics",
            title="Associate Product Manager",
            location="Chicago, IL",
            date="Oct 08",
            apply_url="https://jobs.lever.co/arrivelogistics/80b87c33-325c-4917-aeef-73b082548406",
            is_direct_link=True,
            pay_range="$97,000 - $121,000/year",  # Real data from Lever salaryRange API
            has_written_questions=False,  # Lever lists API: no text questions
            pay_source="Lever salaryRange API",
            questions_source="Lever lists API",
        ),
        JobCard(
            company="TikTok",
            title="Product Strategist Graduate (Global Monetization)",
            location="San Jose, CA",
            date="Oct 12",
            apply_url="https://lifeattiktok.com/search/7673554696239089925",
            is_direct_link=True,
            pay_range="$76,000 - $151,200/year",  # Real data from job page
            has_written_questions=None,  # Could not determine
            pay_source="Job page text",
            questions_source="Could not determine",
        ),
    ]
    
    html_content = render_html_email(sample_jobs, "New PM Jobs", simulate_gmail=simulate_gmail)
    text_content = render_plain_text_email(sample_jobs, "New PM Jobs")
    
    return html_content, text_content
