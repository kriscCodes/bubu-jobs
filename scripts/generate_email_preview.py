#!/usr/bin/env python3
"""Generate email preview artifacts (HTML files and screenshots).

This script renders the sample email to HTML and captures screenshots
at desktop and mobile widths, including a Gmail-stripped version.

Usage:
    python scripts/generate_email_preview.py [--output-dir /path/to/output]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.html_email import render_sample_email_for_preview


def generate_previews(output_dir: Path) -> dict[str, Path]:
    """Generate HTML files and screenshots.
    
    Args:
        output_dir: Directory to save artifacts
    
    Returns:
        Dict mapping artifact names to file paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    
    # Normal version (with background image)
    html_content, text_content = render_sample_email_for_preview(simulate_gmail=False)
    
    html_path = output_dir / "email_preview.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"Wrote HTML: {html_path}")
    artifacts["html"] = html_path
    
    text_path = output_dir / "email_preview.txt"
    text_path.write_text(text_content, encoding="utf-8")
    print(f"Wrote plain text: {text_path}")
    artifacts["text"] = text_path
    
    # Gmail-stripped version (no background images)
    gmail_html, _ = render_sample_email_for_preview(simulate_gmail=True)
    gmail_html_path = output_dir / "email_preview_gmail.html"
    gmail_html_path.write_text(gmail_html, encoding="utf-8")
    print(f"Wrote Gmail-stripped HTML: {gmail_html_path}")
    artifacts["gmail_html"] = gmail_html_path
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            
            # Desktop screenshot (normal version)
            desktop_page = browser.new_page(viewport={"width": 700, "height": 1200})
            desktop_page.set_content(html_content)
            desktop_page.wait_for_load_state("networkidle")
            desktop_screenshot = output_dir / "email_preview_desktop.png"
            desktop_page.screenshot(path=str(desktop_screenshot), full_page=True)
            print(f"Wrote desktop screenshot: {desktop_screenshot}")
            artifacts["desktop_png"] = desktop_screenshot
            desktop_page.close()
            
            # Mobile screenshot (normal version)
            mobile_page = browser.new_page(viewport={"width": 375, "height": 812})
            mobile_page.set_content(html_content)
            mobile_page.wait_for_load_state("networkidle")
            mobile_screenshot = output_dir / "email_preview_mobile.png"
            mobile_page.screenshot(path=str(mobile_screenshot), full_page=True)
            print(f"Wrote mobile screenshot: {mobile_screenshot}")
            artifacts["mobile_png"] = mobile_screenshot
            mobile_page.close()
            
            # Gmail-stripped desktop screenshot
            gmail_page = browser.new_page(viewport={"width": 700, "height": 1200})
            gmail_page.set_content(gmail_html)
            gmail_page.wait_for_load_state("networkidle")
            gmail_screenshot = output_dir / "email_preview_gmail.png"
            gmail_page.screenshot(path=str(gmail_screenshot), full_page=True)
            print(f"Wrote Gmail screenshot: {gmail_screenshot}")
            artifacts["gmail_png"] = gmail_screenshot
            gmail_page.close()
            
            browser.close()
            
    except ImportError:
        print("Warning: playwright not available, skipping screenshots")
    except Exception as e:
        print(f"Warning: screenshot generation failed: {e}")
    
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate email preview artifacts")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/opt/cursor/artifacts/email_preview"),
        help="Output directory for artifacts",
    )
    args = parser.parse_args()
    
    artifacts = generate_previews(args.output_dir)
    
    print("\nGenerated artifacts:")
    for name, path in artifacts.items():
        print(f"  {name}: {path}")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
