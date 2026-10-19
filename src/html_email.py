"""HTML email generation for job alerts.

This module creates nicely styled HTML emails with:
- Clean vertical list of job rows (one per job, full width)
- Panda hero header
- Pay range and application question badges from real ATS data
- Table-based layout with inline styles for Gmail compatibility
"""
import html
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from urllib.parse import urlsplit

from .config import SOURCE_LABELS, SOURCE_JOBRIGHT
from .direct_links import get_direct_link

LOG = logging.getLogger(__name__)

PANDA_IMAGE_PATH = Path(__file__).parent.parent / "assets" / "panda-hero.jpg"
PANDA_GITHUB_URL = "https://raw.githubusercontent.com/kriscCodes/bubu-jobs/main/assets/panda-hero.jpg"
LEGACY_PANDA_GITHUB_URLS = (
    "https://raw.githubusercontent.com/kriscCodes/bubu-jobs/cursor/resolve-ats-urls-56c4/assets/panda-hero.jpg",
)
PANDA_CID = "panda-hero"  # Content-ID for inline attachment


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
    source: str = ""


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


def _source_label(source: str) -> str:
    if not source:
        return ""
    return SOURCE_LABELS.get(source, source)


def _is_jobright_url(url: str) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return host == "jobright.ai" or host.endswith(".jobright.ai")


def _render_job_row(job: JobCard) -> str:
    """Render a single job as a full-width row."""
    direct_badge = f'<span style="display:inline-block;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:600;background-color:{COLORS["success_light"]};color:{COLORS["success"]};text-transform:uppercase;margin-left:8px;">DIRECT</span>' if job.is_direct_link else ''
    source_label = _source_label(job.source)
    source_badge = (
        f'<span style="display:inline-block;padding:3px 8px;border-radius:10px;font-size:10px;font-weight:600;'
        f'background-color:{COLORS["primary_light"]};color:{COLORS["primary_dark"]};text-transform:uppercase;'
        f'margin-left:8px;">{_escape(source_label)}</span>'
        if source_label else ""
    )
    posted = _escape(job.date) if job.date else ""
    location_line = f"📍 {_escape(job.location)}"
    if posted:
        location_line += f" · {posted}"
    
    pay_display = job.pay_range if job.pay_range else "Pay not listed"
    q_icon, q_label, q_bg = _get_question_badge(job.has_written_questions)
    
    return f'''<tr>
    <td style="padding:12px 0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{COLORS['white']};border:1px solid {COLORS['gray_200']};border-radius:12px;">
            <tr>
                <td style="padding:16px;">
                    <!-- Row 1: Company + source / Direct badges -->
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td>
                                <span style="font-size:12px;color:{COLORS['gray_500']};text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">{_escape(job.company)}</span>
                                {source_badge}
                                {direct_badge}
                            </td>
                        </tr>
                    </table>
                    
                    <!-- Row 2: Job title -->
                    <h3 style="font-size:16px;font-weight:700;color:{COLORS['gray_900']};margin:8px 0 10px 0;line-height:1.4;">{_escape(job.title)}</h3>
                    
                    <!-- Row 3: Location + posted date + Pay -->
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;">
                        <tr>
                            <td style="width:50%;vertical-align:top;">
                                <span style="font-size:13px;color:{COLORS['gray_500']};">{location_line}</span>
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


def render_html_email(jobs: list[JobCard], subject: str = "New PM Jobs", use_cid: bool = False) -> str:
    """Render a complete HTML email with a vertical list of job rows.
    
    Features:
    - Clean vertical list layout (one row per job, full width)
    - Panda hero image (CID attachment for email, hosted URL for preview)
    - Table-based layout with inline styles for Gmail compatibility
    - No JavaScript, no CSS pseudo-selectors
    
    Args:
        jobs: List of JobCard objects to render
        subject: Email subject line
        use_cid: If True, use cid:panda-hero for image (for real email sending).
                 If False, use hosted GitHub URL (for browser preview).
    """
    timestamp = datetime.now().strftime("%B %d, %Y")
    direct_count = sum(1 for j in jobs if j.is_direct_link)
    source_counts: dict[str, int] = {}
    for job in jobs:
        label = _source_label(job.source) or ("Jobright" if _is_jobright_url(job.apply_url) else "Other")
        source_counts[label] = source_counts.get(label, 0) + 1
    source_summary = " · ".join(f"{count} {label}" for label, count in source_counts.items())
    num_jobs = len(jobs)
    
    job_rows = "\n".join(_render_job_row(job) for job in jobs)
    panda_url = f"cid:{PANDA_CID}" if use_cid else PANDA_GITHUB_URL
    
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
                                                    <span style="font-size:13px;color:{COLORS['gray_700']};margin-left:6px;vertical-align:middle;">{_escape(source_summary)}</span>
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
        source_label = _source_label(job.source) or ("Jobright" if _is_jobright_url(job.apply_url) else "listing")
        link_type = "Direct" if job.is_direct_link else source_label
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
            f"   Source: {source_label}",
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
        date = job.get("date") or job.get("date_posted", "")
        fallback_url = job.get("canonical_apply_url") or job.get("source_url", job.get("jobright_url", ""))
        work_model = job.get("work_model", "")
        ats = job.get("ats", "")
        pay_range = job.get("pay_range", "")
        has_written_questions = job.get("has_written_questions")
        source = job.get("source") or SOURCE_JOBRIGHT
        
        direct_link = get_direct_link(company, title, location)
        apply_url = direct_link.direct_url if direct_link else fallback_url
        is_direct = bool(direct_link) or not _is_jobright_url(apply_url)
        
        cards.append(JobCard(
            company=company,
            title=title,
            location=location,
            date=date,
            apply_url=apply_url,
            is_direct_link=is_direct,
            source_note=direct_link.note if direct_link else "",
            work_model=work_model,
            ats=ats,
            pay_range=pay_range,
            has_written_questions=has_written_questions,
            source=source,
        ))
    
    return cards


def render_sample_email_for_preview(use_cid: bool = False) -> tuple[str, str]:
    """Render a sample email with REAL enriched job data for preview/testing.
    
    Args:
        use_cid: If True, use cid:panda-hero for image (for real email).
                 If False, use hosted GitHub URL (for browser preview).
    
    Returns:
        Tuple of (html_content, plain_text_content)
    """
    sample_jobs = [
        JobCard(
            company="Google",
            title="Product Manager I, Ads Sellside Apps",
            location="Mountain View, CA, USA",
            date="Oct 16",
            apply_url="https://www.google.com/about/careers/applications/jobs/results/98591892920246982",
            is_direct_link=True,
            source="findyourrolefirst",
            pay_range="",
            has_written_questions=None,
        ),
        JobCard(
            company="Microsoft",
            title="Product Manager",
            location="Remote in USA",
            date="Oct 15",
            apply_url="https://apply.careers.microsoft.com/careers/job/1970393557027388",
            is_direct_link=True,
            source="simplify",
            pay_range="",
            has_written_questions=None,
        ),
        JobCard(
            company="LSEG",
            title="Senior Associate Product Manager - Enterprise AI",
            location="NYC",
            date="Oct 13",
            apply_url="https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/New-York-City-United-States/Senior-Associate-Product-Manager--Enterprise-AI_R0124288",
            is_direct_link=True,
            source="simplify",
            pay_range="",
            has_written_questions=None,
        ),
        JobCard(
            company="Natera",
            title="(Associate) Product Manager, Organ Health",
            location="Austin, TX",
            date="Oct 13",
            apply_url="https://job-boards.greenhouse.io/natera/jobs/6217258004",
            is_direct_link=True,
            source="findyourrolefirst",
            pay_range="",
            has_written_questions=False,
        ),
        JobCard(
            company="Figma",
            title="Associate Product Manager",
            location="SF",
            date="Oct 7",
            apply_url="https://boards.greenhouse.io/figma/jobs/6180116004",
            is_direct_link=True,
            source="simplify",
            pay_range="",
            has_written_questions=False,
        ),
    ]
    
    html_content = render_html_email(sample_jobs, "New PM Jobs", use_cid=use_cid)
    text_content = render_plain_text_email(sample_jobs, "New PM Jobs")
    
    return html_content, text_content
