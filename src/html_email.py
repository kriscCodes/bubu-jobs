"""HTML email generation for job alerts.

This module creates nicely styled HTML emails with:
- Clean vertical list of job rows (one per job, full width)
- Panda hero header
- Pay range and application question badges from real ATS data
- Table-based layout with inline styles for Gmail compatibility
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
    """Data for a single job row in the email."""
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
    "gray_50": "#f9fafb",
    "gray_100": "#f3f4f6",
    "gray_200": "#e5e7eb",
    "gray_300": "#d1d5db",
    "gray_500": "#6b7280",
    "gray_700": "#374151",
    "gray_900": "#111827",
    "white": "#ffffff",
    "pink_50": "#fdf2f8",
    "bg_fallback": "#e8d5f0",
}


def _escape(text: str) -> str:
    """HTML escape text."""
    return html.escape(str(text))


def _get_question_badge(has_written_questions: Optional[bool]) -> tuple[str, str, str]:
    """Return (icon, label, bg_color) for question badge."""
    if has_written_questions is True:
        return ("✍️", "Written response", COLORS["warning_light"])
    elif has_written_questions is False:
        return ("⚡", "Quick apply", COLORS["success_light"])
    else:
        return ("❓", "Unknown", COLORS["gray_200"])


def _render_job_row(job: JobCard) -> str:
    """Render a single job as a full-width row."""
    direct_badge = f'<span style="display:inline-block;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:600;background-color:{COLORS["success_light"]};color:{COLORS["success"]};text-transform:uppercase;margin-left:8px;">DIRECT</span>' if job.is_direct_link else ''
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_badge(job.has_written_questions)
    
    return f'''<tr>
    <td style="padding:12px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['white']};border:1px solid {COLORS['gray_200']};border-radius:12px;">
            <tr>
                <td style="padding:16px;">
                    <!-- Row 1: Company + Direct badge -->
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td>
                                <span style="font-size:12px;color:{COLORS['gray_500']};text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">{_escape(job.company)}</span>
                                {direct_badge}
                            </td>
                        </tr>
                    </table>
                    
                    <!-- Row 2: Job title -->
                    <h3 style="font-size:16px;font-weight:700;color:{COLORS['gray_900']};margin:8px 0 10px 0;line-height:1.4;">{_escape(job.title)}</h3>
                    
                    <!-- Row 3: Location + Pay -->
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                        <tr>
                            <td style="width:50%;vertical-align:top;">
                                <span style="font-size:13px;color:{COLORS['gray_500']};">📍 {_escape(job.location)}</span>
                            </td>
                            <td style="width:50%;vertical-align:top;text-align:right;">
                                <span style="font-size:13px;font-weight:600;color:{COLORS['primary']};">💰 {_escape(pay_display)}</span>
                            </td>
                        </tr>
                    </table>
                    
                    <!-- Row 4: Question badge + Apply button -->
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td style="vertical-align:middle;">
                                <span style="display:inline-block;padding:4px 10px;border-radius:6px;font-size:11px;background-color:{q_bg};color:{COLORS['gray_700']};">{q_icon} {q_label}</span>
                            </td>
                            <td style="text-align:right;vertical-align:middle;">
                                <a href="{_escape(job.apply_url)}" style="display:inline-block;background-color:{COLORS['primary']};color:{COLORS['white']};text-decoration:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600;">Apply →</a>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </td>
</tr>'''


def render_html_email(jobs: list[JobCard], subject: str = "New PM Jobs") -> str:
    """Render a complete HTML email with a vertical list of job rows.
    
    Features:
    - Clean vertical list layout (one row per job, full width)
    - Panda hero header with both background-image and inline <img>
    - Table-based layout with inline styles for Gmail compatibility
    - No JavaScript, no CSS pseudo-selectors
    """
    timestamp = datetime.now().strftime("%B %d, %Y")
    direct_count = sum(1 for j in jobs if j.is_direct_link)
    jobright_count = len(jobs) - direct_count
    num_jobs = len(jobs)
    
    job_rows = "\n".join(_render_job_row(job) for job in jobs)
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
        @media only screen and (max-width: 560px) {{
            .wrapper {{ padding: 12px !important; }}
            .hero-cell {{ padding: 20px 16px !important; }}
            .content-cell {{ padding: 16px !important; }}
        }}
    </style>
</head>
<body style="margin:0;padding:0;background-color:{COLORS['bg_fallback']};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;line-height:1.5;">
    
    <!-- Outer wrapper -->
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['bg_fallback']};">
        <tr>
            <td align="center" style="padding:20px 0;">
                
                <!-- Main container 560px -->
                <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" class="wrapper" style="max-width:560px;width:100%;">
                    
                    <!-- Panda Hero Image -->
                    <tr>
                        <td>
                            <img src="{panda_url}" alt="Bubu the Panda - Your Job Hunting Buddy" width="560" style="display:block;width:100%;max-width:560px;height:auto;border-radius:16px 16px 0 0;" />
                        </td>
                    </tr>
                    
                    <!-- Header Text -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['primary']};">
                                <tr>
                                    <td class="hero-cell" style="padding:20px 24px;text-align:center;">
                                        <h1 style="color:{COLORS['white']};margin:0 0 6px 0;font-size:24px;font-weight:700;">🎋 {_escape(subject)}</h1>
                                        <p style="color:rgba(255,255,255,0.95);margin:0;font-size:14px;">{num_jobs} new posting{"s" if num_jobs != 1 else ""} • {timestamp}</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Stats Bar -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['white']};">
                                <tr>
                                    <td style="padding:14px 24px;border-bottom:1px solid {COLORS['gray_200']};">
                                        <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                            <tr>
                                                <td style="text-align:center;width:50%;">
                                                    <span style="display:inline-block;width:8px;height:8px;background-color:{COLORS['success']};border-radius:50%;vertical-align:middle;"></span>
                                                    <span style="font-size:13px;color:{COLORS['gray_700']};margin-left:6px;vertical-align:middle;">{direct_count} Direct</span>
                                                </td>
                                                <td style="text-align:center;width:50%;">
                                                    <span style="display:inline-block;width:8px;height:8px;background-color:{COLORS['warning']};border-radius:50%;vertical-align:middle;"></span>
                                                    <span style="font-size:13px;color:{COLORS['gray_700']};margin-left:6px;vertical-align:middle;">{jobright_count} Jobright</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Job List -->
                    <tr>
                        <td>
                            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['white']};border-radius:0 0 16px 16px;">
                                <tr>
                                    <td class="content-cell" style="padding:20px 24px;">
                                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                                            {job_rows}
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding:20px;text-align:center;">
                            <p style="font-size:12px;color:{COLORS['gray_500']};margin:0 0 6px 0;">Sent with 🐼 by Bubu Jobs</p>
                            <p style="font-size:11px;color:{COLORS['gray_300']};margin:0;">
                                <a href="#" style="color:{COLORS['primary']};text-decoration:none;">Unsubscribe</a> • 
                                <a href="#" style="color:{COLORS['primary']};text-decoration:none;">Preferences</a>
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
            f"{i}. {job.company}",
            f"   Title: {job.title}",
            f"   Location: {job.location}",
            f"   Pay: {pay_display}",
            f"   {q_status}",
            f"   Link type: {link_type}",
        ])
        if job.work_model:
            lines.append(f"   Work model: {job.work_model}")
        if job.ats:
            lines.append(f"   ATS: {job.ats}")
        if job.date:
            lines.append(f"   Date: {job.date}")
        lines.extend([
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


def render_sample_email_for_preview() -> tuple[str, str]:
    """Render a sample email with REAL enriched job data for preview/testing.
    
    Returns:
        Tuple of (html_content, plain_text_content)
    """
    sample_jobs = [
        JobCard(
            company="Roblox",
            title="Associate Product Manager, Early Career",
            location="San Mateo, CA",
            date="Oct 09",
            apply_url="https://careers.roblox.com/jobs/8143976?gh_jid=8143976",
            is_direct_link=True,
            pay_range="",
            has_written_questions=False,
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
            pay_range="$111,200 - $126,900",
            has_written_questions=None,
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
            pay_range="$85,000 - $95,000/year",
            has_written_questions=False,
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
            pay_range="$97,000 - $121,000/year",
            has_written_questions=False,
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
            pay_range="$76,000 - $151,200/year",
            has_written_questions=None,
            pay_source="Job page text",
            questions_source="Could not determine",
        ),
    ]
    
    html_content = render_html_email(sample_jobs, "New PM Jobs")
    text_content = render_plain_text_email(sample_jobs, "New PM Jobs")
    
    return html_content, text_content
