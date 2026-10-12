"""HTML email generation for job alerts.

This module creates nicely styled HTML emails with job cards, a cute panda hero,
badges for direct vs. Jobright links, pay range display, application question indicators,
and a CSS carousel that degrades gracefully in Gmail.
"""
import base64
import html
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .direct_links import get_direct_link, DirectLink

LOG = logging.getLogger(__name__)

PANDA_IMAGE_PATH = Path(__file__).parent.parent / "assets" / "panda-hero.jpg"
PANDA_GITHUB_URL = "https://raw.githubusercontent.com/kristinaglass/bubu-jobs/main/assets/panda-hero.jpg"


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
    pay_range: str = ""  # "Pay not listed" if unknown
    has_written_questions: Optional[bool] = None  # None = Unknown, True = Yes, False = No


def _get_panda_base64() -> str:
    """Get panda image as base64 data URI for inline embedding."""
    try:
        if PANDA_IMAGE_PATH.exists():
            with open(PANDA_IMAGE_PATH, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
                return f"data:image/jpeg;base64,{data}"
    except Exception as e:
        LOG.warning("Failed to load panda image: %s", e)
    return PANDA_GITHUB_URL


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
    "pink_200": "#fbcfe8",
}


def _escape(text: str) -> str:
    """HTML escape text."""
    return html.escape(str(text))


def _get_question_indicator(has_written_questions: Optional[bool]) -> tuple[str, str, str]:
    """Return (icon, label, bg_color) for question indicator."""
    if has_written_questions is True:
        return ("✍️", "Written response required", COLORS["warning_light"])
    elif has_written_questions is False:
        return ("⚡", "Quick apply", COLORS["success_light"])
    else:
        return ("❓", "Unknown", COLORS["gray_200"])


def _render_job_card_carousel(job: JobCard, index: int, total: int) -> str:
    """Render a single job card for the carousel."""
    badge_class = "badge-direct" if job.is_direct_link else "badge-jobright"
    badge_text = "Direct" if job.is_direct_link else "Jobright"
    badge_bg = COLORS["success_light"] if job.is_direct_link else COLORS["warning_light"]
    badge_color = COLORS["success"] if job.is_direct_link else COLORS["warning"]
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_indicator(job.has_written_questions)
    
    return f'''
    <div class="carousel-slide" style="min-width: 280px; max-width: 320px; flex-shrink: 0; background-color: {COLORS['white']}; border: 1px solid {COLORS['gray_200']}; border-radius: 12px; padding: 20px; margin: 0 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.06);">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
                <td>
                    <p style="font-size: 12px; color: {COLORS['gray_500']}; margin: 0 0 4px 0; text-transform: uppercase; letter-spacing: 0.5px;">{_escape(job.company)}</p>
                </td>
                <td style="text-align: right;">
                    <span style="display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; background-color: {badge_bg}; color: {badge_color}; text-transform: uppercase;">{badge_text}</span>
                </td>
            </tr>
            <tr>
                <td colspan="2">
                    <h3 style="font-size: 16px; font-weight: 700; color: {COLORS['gray_900']}; margin: 8px 0; line-height: 1.3;">{_escape(job.title)}</h3>
                </td>
            </tr>
            <tr>
                <td colspan="2">
                    <p style="font-size: 13px; color: {COLORS['gray_500']}; margin: 0 0 6px 0;">📍 {_escape(job.location)}</p>
                </td>
            </tr>
            <tr>
                <td colspan="2">
                    <p style="font-size: 14px; font-weight: 600; color: {COLORS['primary']}; margin: 0 0 8px 0;">💰 {_escape(pay_display)}</p>
                </td>
            </tr>
            <tr>
                <td colspan="2">
                    <span style="display: inline-block; padding: 4px 10px; border-radius: 8px; font-size: 11px; background-color: {q_bg}; color: {COLORS['gray_700']};">{q_icon} {q_label}</span>
                </td>
            </tr>
            <tr>
                <td colspan="2" style="padding-top: 16px;">
                    <a href="{_escape(job.apply_url)}" style="display: block; background-color: {COLORS['primary']}; color: {COLORS['white']}; text-decoration: none; padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: 600; text-align: center;">Apply Now →</a>
                </td>
            </tr>
        </table>
        <p style="font-size: 11px; color: {COLORS['gray_300']}; margin: 12px 0 0 0; text-align: center;">{index + 1} of {total}</p>
    </div>
    '''


def _render_job_card_stacked(job: JobCard) -> str:
    """Render a single job card for stacked/list layout (Gmail fallback)."""
    badge_text = "Direct" if job.is_direct_link else "Jobright"
    badge_bg = COLORS["success_light"] if job.is_direct_link else COLORS["warning_light"]
    badge_color = COLORS["success"] if job.is_direct_link else COLORS["warning"]
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_indicator(job.has_written_questions)
    
    return f'''
    <tr>
        <td style="padding: 12px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border: 1px solid {COLORS['gray_200']}; border-radius: 12px;">
                <tr>
                    <td style="padding: 16px;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td>
                                    <span style="font-size: 12px; color: {COLORS['gray_500']}; text-transform: uppercase; letter-spacing: 0.5px;">{_escape(job.company)}</span>
                                </td>
                                <td style="text-align: right;">
                                    <span style="display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; background-color: {badge_bg}; color: {badge_color}; text-transform: uppercase;">{badge_text}</span>
                                </td>
                            </tr>
                        </table>
                        <h3 style="font-size: 16px; font-weight: 700; color: {COLORS['gray_900']}; margin: 8px 0 6px 0; line-height: 1.3;">{_escape(job.title)}</h3>
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td style="width: 50%;">
                                    <p style="font-size: 13px; color: {COLORS['gray_500']}; margin: 0;">📍 {_escape(job.location)}</p>
                                </td>
                                <td style="width: 50%;">
                                    <p style="font-size: 14px; font-weight: 600; color: {COLORS['primary']}; margin: 0;">💰 {_escape(pay_display)}</p>
                                </td>
                            </tr>
                        </table>
                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top: 10px;">
                            <tr>
                                <td>
                                    <span style="display: inline-block; padding: 4px 10px; border-radius: 8px; font-size: 11px; background-color: {q_bg}; color: {COLORS['gray_700']};">{q_icon} {q_label}</span>
                                </td>
                                <td style="text-align: right;">
                                    <a href="{_escape(job.apply_url)}" style="display: inline-block; background-color: {COLORS['primary']}; color: {COLORS['white']}; text-decoration: none; padding: 10px 20px; border-radius: 8px; font-size: 13px; font-weight: 600;">Apply →</a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''


def render_html_email(jobs: list[JobCard], subject: str = "New PM Jobs") -> str:
    """Render a complete HTML email with job cards and CSS carousel.
    
    Uses progressive enhancement:
    - Full CSS carousel with radio/:checked for Apple Mail/iOS
    - Horizontal scrollable cards for clients that strip :checked
    - Stacked list as ultimate fallback
    
    Args:
        jobs: List of JobCard objects to render
        subject: Email subject (shown in header)
    
    Returns:
        Complete HTML email string
    """
    panda_src = _get_panda_base64()
    timestamp = datetime.now().strftime("%B %d, %Y")
    direct_count = sum(1 for j in jobs if j.is_direct_link)
    jobright_count = len(jobs) - direct_count
    
    # Carousel slides
    carousel_slides = "\n".join(
        _render_job_card_carousel(job, i, len(jobs)) 
        for i, job in enumerate(jobs)
    )
    
    # Radio inputs for carousel (Apple Mail/iOS)
    radio_inputs = "\n".join(
        f'<input type="radio" name="carousel" id="slide{i}" style="display:none;" {"checked" if i == 0 else ""}>'
        for i in range(len(jobs))
    )
    
    # CSS for carousel navigation (prev/next labels)
    carousel_nav_css = ""
    carousel_nav_html = ""
    if len(jobs) > 1:
        # Generate CSS rules for showing slides based on checked radio
        slide_css_rules = []
        for i in range(len(jobs)):
            slide_css_rules.append(f"#slide{i}:checked ~ .carousel-track .slide-{i} {{ display: flex; }}")
        carousel_nav_css = "\n".join(slide_css_rules)
        
        # Navigation labels
        nav_items = []
        for i in range(len(jobs)):
            prev_i = (i - 1) % len(jobs)
            next_i = (i + 1) % len(jobs)
            nav_items.append(f'''
            <div class="nav-{i}" style="display: none; justify-content: center; gap: 12px; margin-top: 16px;">
                <label for="slide{prev_i}" style="display: inline-block; padding: 8px 16px; background-color: {COLORS['gray_100']}; border-radius: 8px; cursor: pointer; font-size: 14px;">← Prev</label>
                <label for="slide{next_i}" style="display: inline-block; padding: 8px 16px; background-color: {COLORS['primary']}; color: white; border-radius: 8px; cursor: pointer; font-size: 14px;">Next →</label>
            </div>
            ''')
        carousel_nav_html = "\n".join(nav_items)
        
        # CSS to show correct nav based on checked radio
        nav_css_rules = [f"#slide{i}:checked ~ .carousel-nav .nav-{i} {{ display: flex; }}" for i in range(len(jobs))]
        carousel_nav_css += "\n" + "\n".join(nav_css_rules)
    
    # Stacked fallback for Gmail (Gmail strips :checked pseudo-class)
    stacked_cards = "\n".join(_render_job_card_stacked(job) for job in jobs)
    
    return f'''<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{_escape(subject)}</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
    <style type="text/css">
        /* Reset */
        body, table, td {{ margin: 0; padding: 0; }}
        img {{ border: 0; display: block; max-width: 100%; }}
        
        /* Gmail-safe stacked layout (default) */
        .gmail-show {{ display: block !important; }}
        .gmail-hide {{ display: none !important; }}
        
        /* Carousel styles for Apple Mail/iOS that support :checked */
        @supports selector(:checked) {{
            .gmail-show {{ display: none !important; }}
            .gmail-hide {{ display: block !important; }}
            
            .carousel-track {{
                display: flex;
                overflow-x: auto;
                scroll-snap-type: x mandatory;
                -webkit-overflow-scrolling: touch;
                gap: 0;
                padding: 8px 0;
            }}
            
            .carousel-slide {{
                scroll-snap-align: center;
            }}
            
            {carousel_nav_css}
        }}
        
        /* Mobile responsiveness */
        @media only screen and (max-width: 600px) {{
            .wrapper {{ padding: 12px !important; }}
            .header-content {{ padding: 16px !important; }}
            .carousel-slide {{ min-width: 260px !important; max-width: 280px !important; }}
        }}
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: {COLORS['pink_50']}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.5;">
    <div class="wrapper" style="width: 100%; max-width: 640px; margin: 0 auto; padding: 20px;">
        
        <!-- Hero Header with Panda -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background: linear-gradient(135deg, {COLORS['primary']} 0%, {COLORS['primary_dark']} 100%); border-radius: 16px 16px 0 0;">
            <tr>
                <td class="header-content" style="padding: 24px; text-align: center;">
                    <!-- Panda Image -->
                    <img src="{panda_src}" alt="Bubu the Job-Hunting Panda" width="140" height="140" style="width: 140px; height: 140px; border-radius: 50%; margin: 0 auto 16px auto; display: block; background-color: {COLORS['white']}; object-fit: cover; border: 4px solid rgba(255,255,255,0.3);">
                    
                    <h1 style="color: {COLORS['white']}; margin: 0 0 8px 0; font-size: 26px; font-weight: 700;">🎋 {_escape(subject)}</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 0; font-size: 15px;">{len(jobs)} new posting{"s" if len(jobs) != 1 else ""} • {timestamp}</p>
                </td>
            </tr>
        </table>
        
        <!-- Stats Bar -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']};">
            <tr>
                <td style="padding: 16px 24px; border-bottom: 1px solid {COLORS['gray_200']};">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td style="text-align: center; width: 50%;">
                                <span style="display: inline-block; width: 10px; height: 10px; background-color: {COLORS['success']}; border-radius: 50%; vertical-align: middle;"></span>
                                <span style="font-size: 14px; color: {COLORS['gray_700']}; margin-left: 6px; vertical-align: middle;">{direct_count} Direct</span>
                            </td>
                            <td style="text-align: center; width: 50%;">
                                <span style="display: inline-block; width: 10px; height: 10px; background-color: {COLORS['warning']}; border-radius: 50%; vertical-align: middle;"></span>
                                <span style="font-size: 14px; color: {COLORS['gray_700']}; margin-left: 6px; vertical-align: middle;">{jobright_count} Jobright</span>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
        
        <!-- Content Area -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border-radius: 0 0 16px 16px;">
            <tr>
                <td style="padding: 24px;">
                    
                    <!-- CSS Carousel (Apple Mail/iOS) - Hidden in Gmail -->
                    <div class="gmail-hide" style="display: none;">
                        {radio_inputs}
                        
                        <div class="carousel-track" style="display: flex; overflow-x: auto; scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch; padding: 8px 0; margin: 0 -8px;">
                            {carousel_slides}
                        </div>
                        
                        <div class="carousel-nav" style="text-align: center;">
                            {carousel_nav_html}
                        </div>
                        
                        <p style="text-align: center; font-size: 12px; color: {COLORS['gray_500']}; margin: 16px 0 0 0;">← Swipe or use arrows to browse jobs →</p>
                    </div>
                    
                    <!-- Stacked Cards (Gmail Fallback) -->
                    <div class="gmail-show" style="display: block;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            {stacked_cards}
                        </table>
                    </div>
                    
                </td>
            </tr>
        </table>
        
        <!-- Footer -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
                <td style="padding: 24px; text-align: center;">
                    <p style="font-size: 12px; color: {COLORS['gray_500']}; margin: 0 0 8px 0;">Sent with 🐼 by Bubu Jobs</p>
                    <p style="font-size: 11px; color: {COLORS['gray_300']}; margin: 0;">
                        <a href="#" style="color: {COLORS['primary']}; text-decoration: none;">Unsubscribe</a> • 
                        <a href="#" style="color: {COLORS['primary']}; text-decoration: none;">Preferences</a>
                    </p>
                </td>
            </tr>
        </table>
        
    </div>
</body>
</html>'''


def render_plain_text_email(jobs: list[JobCard], subject: str = "New PM Jobs") -> str:
    """Render a plain text alternative for the email.
    
    Args:
        jobs: List of JobCard objects
        subject: Email subject
    
    Returns:
        Plain text email string
    """
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
            q_status = "Quick apply (no essays)"
        else:
            q_status = "Application questions: Unknown"
        
        lines.extend([
            f"{i}. {job.company} - {job.title}",
            f"   Location: {job.location}",
            f"   Pay: {pay_display}",
            f"   {q_status}",
        ])
        if job.work_model:
            lines.append(f"   Work model: {job.work_model}")
        if job.ats:
            lines.append(f"   ATS: {job.ats}")
        lines.extend([
            f"   Posted: {job.date}",
            f"   Link type: {link_type}",
            f"   Apply: {job.apply_url}",
            "",
        ])
    
    lines.extend([
        "---",
        "Sent with 🐼 by Bubu Jobs",
    ])
    
    return "\n".join(lines)


def create_job_cards_from_jobs(jobs: list[dict]) -> list[JobCard]:
    """Convert job dicts to JobCard objects, looking up direct links.
    
    Args:
        jobs: List of job dicts with company, title, location, date, source_url
    
    Returns:
        List of JobCard objects with direct links where available
    """
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


def render_sample_email_for_preview() -> tuple[str, str]:
    """Render a sample email with realistic job data for preview/testing.
    
    Returns:
        Tuple of (html_content, plain_text_content)
    """
    sample_jobs = [
        JobCard(
            company="Roblox",
            title="Associate Product Manager, Early Career",
            location="San Mateo, CA",
            date="Oct 09",
            apply_url="https://careers.roblox.com/jobs/8143976",
            is_direct_link=True,
            pay_range="$120,000 - $150,000",
            has_written_questions=False,
            ats="Greenhouse",
        ),
        JobCard(
            company="Databricks",
            title="Associate Product Manager, New Grad (2027 Start)",
            location="Bellevue, WA",
            date="Oct 11",
            apply_url="https://databricks.com/company/careers/open-positions/job?gh_jid=7586263002",
            is_direct_link=True,
            pay_range="$130,000 - $160,000",
            has_written_questions=True,
            ats="Greenhouse",
        ),
        JobCard(
            company="TikTok",
            title="Product Strategist Graduate (Global Monetization)",
            location="San Jose, CA",
            date="Oct 12",
            apply_url="https://lifeattiktok.com/search/7673554696239089925",
            is_direct_link=True,
            pay_range="Pay not listed",
            has_written_questions=None,
            ats="Custom",
        ),
        JobCard(
            company="Capital One",
            title="Senior Associate, Product Manager - Business Cards",
            location="New York, NY",
            date="Oct 10",
            apply_url="https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/New-York-NY/Senior-Associate--Product-Manager_R1003243-2",
            is_direct_link=True,
            pay_range="$106,700 - $133,300",
            has_written_questions=False,
            ats="Workday",
        ),
        JobCard(
            company="Adobe",
            title="2027 MBA University Graduate - Product Manager",
            location="San Jose, CA",
            date="Oct 09",
            apply_url="https://adobe.wd5.myworkdayjobs.com/external_experienced/job/San-Jose/XMLNAME-2027-MBA-University-Graduate---Product-Manager_R171900",
            is_direct_link=True,
            pay_range="$120,000 - $180,000",
            has_written_questions=True,
            ats="Workday",
        ),
    ]
    
    html_content = render_html_email(sample_jobs, "New PM Jobs")
    text_content = render_plain_text_email(sample_jobs, "New PM Jobs")
    
    return html_content, text_content
