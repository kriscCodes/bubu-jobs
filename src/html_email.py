"""HTML email generation for job alerts.

This module creates nicely styled HTML emails with job cards, a panda background,
badges for direct vs. Jobright links, pay range display, application question indicators,
and a layout that degrades gracefully in Gmail.
"""
import html
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .direct_links import get_direct_link, DirectLink

LOG = logging.getLogger(__name__)

PANDA_IMAGE_PATH = Path(__file__).parent.parent / "assets" / "panda-hero.jpg"
# Use main branch URL - image will be available after PR merge
# During development, fall back to branch URL
PANDA_GITHUB_URL_MAIN = "https://raw.githubusercontent.com/kriscCodes/bubu-jobs/main/assets/panda-hero.jpg"
PANDA_GITHUB_URL_BRANCH = "https://raw.githubusercontent.com/kriscCodes/bubu-jobs/cursor/resolve-ats-urls-56c4/assets/panda-hero.jpg"
PANDA_GITHUB_URL = PANDA_GITHUB_URL_BRANCH  # Use branch URL until merged


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
    pay_range: str = ""  # Empty string means "Pay not listed"
    has_written_questions: Optional[bool] = None  # None = Unknown, True = Yes, False = No


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
    "bg_fallback": "#e8d5f0",
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


def _render_job_card_stacked(job: JobCard) -> str:
    """Render a single job card for stacked layout."""
    badge_text = "Direct" if job.is_direct_link else "Jobright"
    badge_bg = COLORS["success_light"] if job.is_direct_link else COLORS["warning_light"]
    badge_color = COLORS["success"] if job.is_direct_link else COLORS["warning"]
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_indicator(job.has_written_questions)
    
    return f'''
    <tr>
        <td style="padding: 8px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border: 1px solid {COLORS['gray_200']}; border-radius: 12px;">
                <tr>
                    <td style="padding: 16px;">
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td>
                                    <span style="font-size: 11px; color: {COLORS['gray_500']}; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;">{_escape(job.company)}</span>
                                </td>
                                <td style="text-align: right;">
                                    <span style="display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 10px; font-weight: 600; background-color: {badge_bg}; color: {badge_color}; text-transform: uppercase;">{badge_text}</span>
                                </td>
                            </tr>
                        </table>
                        <h3 style="font-size: 15px; font-weight: 700; color: {COLORS['gray_900']}; margin: 6px 0; line-height: 1.3;">{_escape(job.title)}</h3>
                        <p style="font-size: 13px; color: {COLORS['gray_500']}; margin: 0 0 4px 0;">📍 {_escape(job.location)}</p>
                        <p style="font-size: 13px; font-weight: 600; color: {COLORS['primary']}; margin: 0 0 8px 0;">💰 {_escape(pay_display)}</p>
                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td>
                                    <span style="display: inline-block; padding: 4px 8px; border-radius: 6px; font-size: 10px; background-color: {q_bg}; color: {COLORS['gray_700']};">{q_icon} {q_label}</span>
                                </td>
                                <td style="text-align: right;">
                                    <a href="{_escape(job.apply_url)}" style="display: inline-block; background-color: {COLORS['primary']}; color: {COLORS['white']}; text-decoration: none; padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 600;">Apply →</a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
    '''


def render_html_email(jobs: list[JobCard], subject: str = "New PM Jobs", simulate_gmail: bool = False) -> str:
    """Render a complete HTML email with job cards.
    
    Uses a bulletproof background image approach with VML for Outlook,
    hosted image URL for modern clients, and solid color fallback.
    
    Args:
        jobs: List of JobCard objects to render
        subject: Email subject (shown in header)
        simulate_gmail: If True, render Gmail-stripped version (no background images)
    
    Returns:
        Complete HTML email string
    """
    timestamp = datetime.now().strftime("%B %d, %Y")
    direct_count = sum(1 for j in jobs if j.is_direct_link)
    jobright_count = len(jobs) - direct_count
    
    stacked_cards = "\n".join(_render_job_card_stacked(job) for job in jobs)
    
    bg_image_url = PANDA_GITHUB_URL
    bg_fallback = COLORS["bg_fallback"]
    
    if simulate_gmail:
        background_style = f"background-color: {bg_fallback};"
        vml_background = ""
        hero_bg_style = f"background-color: {COLORS['primary']};"
    else:
        background_style = f"background-color: {bg_fallback};"
        hero_bg_style = f"background-color: {COLORS['primary']}; background-image: url('{bg_image_url}'); background-repeat: no-repeat; background-position: center center; background-size: cover; background-blend-mode: soft-light;"
        vml_background = f'''<!--[if gte mso 9]>
        <v:background xmlns:v="urn:schemas-microsoft-com:vml" fill="t">
            <v:fill type="frame" src="{bg_image_url}" color="{bg_fallback}"/>
        </v:background>
        <![endif]-->'''
    
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
                <o:AllowPNG/>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <style type="text/css">
        table {{ border-collapse: collapse; }}
        td {{ font-family: Arial, sans-serif; }}
    </style>
    <![endif]-->
    <style type="text/css">
        body, table, td {{ margin: 0; padding: 0; }}
        img {{ border: 0; display: block; max-width: 100%; }}
        a {{ color: {COLORS['primary']}; }}
        
        @media only screen and (max-width: 600px) {{
            .wrapper {{ padding: 12px !important; }}
            .content-cell {{ padding: 16px !important; }}
            .card-table {{ padding: 12px !important; }}
        }}
    </style>
</head>
<body style="margin: 0; padding: 0; {background_style} font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.5;">
    {vml_background}
    
    <!-- Wrapper table for centering -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center" style="padding: 20px 0;">
                
                <!-- Main container - fixed 560px width -->
                <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" class="wrapper" style="max-width: 560px; width: 100%;">
                    
                    <!-- Header Card with Panda Background -->
                    <tr>
                        <td>
                            <!--[if gte mso 9]>
                            <v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:560px;height:180px;">
                                <v:fill type="frame" src="{bg_image_url}" color="{COLORS['primary']}" />
                                <v:textbox inset="0,0,0,0">
                            <![endif]-->
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="{hero_bg_style} border-radius: 16px 16px 0 0;">
                                <tr>
                                    <td style="padding: 40px 24px; text-align: center;">
                                        <h1 style="color: {COLORS['white']}; margin: 0 0 8px 0; font-size: 26px; font-weight: 700; text-shadow: 0 2px 4px rgba(0,0,0,0.3);">🎋 {_escape(subject)}</h1>
                                        <p style="color: rgba(255,255,255,0.95); margin: 0; font-size: 15px; text-shadow: 0 1px 2px rgba(0,0,0,0.2);">{len(jobs)} new posting{"s" if len(jobs) != 1 else ""} • {timestamp}</p>
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
                                    <td style="padding: 14px 24px; border-bottom: 1px solid {COLORS['gray_200']};">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
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
                    
                    <!-- Job Cards -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: {COLORS['white']}; border-radius: 0 0 16px 16px;">
                                <tr>
                                    <td class="content-cell" style="padding: 20px;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                            {stacked_cards}
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
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
                
            </td>
        </tr>
    </table>
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


def render_sample_email_for_preview(simulate_gmail: bool = False) -> tuple[str, str]:
    """Render a sample email with real job data for preview/testing.
    
    IMPORTANT: All pay_range and has_written_questions values are set to 
    "not available" / Unknown since we don't have verified data from 
    actual ATS API queries. Only real, sourced data should be displayed.
    
    Args:
        simulate_gmail: If True, render without background images (Gmail strips them)
    
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
            pay_range="",  # No verified pay data - show "Pay not listed"
            has_written_questions=None,  # No verified data - show "Unknown"
            ats="Greenhouse",
        ),
        JobCard(
            company="Databricks",
            title="Associate Product Manager, New Grad (2027 Start)",
            location="Bellevue, WA",
            date="Oct 11",
            apply_url="https://databricks.com/company/careers/open-positions/job?gh_jid=7586263002",
            is_direct_link=True,
            pay_range="",  # No verified pay data
            has_written_questions=None,  # No verified data
            ats="Greenhouse",
        ),
        JobCard(
            company="TikTok",
            title="Product Strategist Graduate (Global Monetization)",
            location="San Jose, CA",
            date="Oct 12",
            apply_url="https://lifeattiktok.com/search/7673554696239089925",
            is_direct_link=True,
            pay_range="",  # No verified pay data
            has_written_questions=None,  # No verified data
            ats="Custom",
        ),
        JobCard(
            company="Capital One",
            title="Senior Associate, Product Manager - Business Cards",
            location="New York, NY",
            date="Oct 10",
            apply_url="https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/New-York-NY/Senior-Associate--Product-Manager_R1003243-2",
            is_direct_link=True,
            pay_range="",  # No verified pay data
            has_written_questions=None,  # No verified data
            ats="Workday",
        ),
        JobCard(
            company="Adobe",
            title="2027 MBA University Graduate - Product Manager",
            location="San Jose, CA",
            date="Oct 09",
            apply_url="https://adobe.wd5.myworkdayjobs.com/external_experienced/job/San-Jose/XMLNAME-2027-MBA-University-Graduate---Product-Manager_R171900",
            is_direct_link=True,
            pay_range="",  # No verified pay data
            has_written_questions=None,  # No verified data
            ats="Workday",
        ),
    ]
    
    html_content = render_html_email(sample_jobs, "New PM Jobs", simulate_gmail=simulate_gmail)
    text_content = render_plain_text_email(sample_jobs, "New PM Jobs")
    
    return html_content, text_content
