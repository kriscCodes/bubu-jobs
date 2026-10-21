#!/usr/bin/env python3
"""Generate email preview artifacts (HTML files and screenshots).

This script renders the sample email to HTML and captures screenshots
at desktop and mobile widths.

Usage:
    python scripts/generate_email_preview.py [--output-dir /path/to/output]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.html_email import render_sample_email_for_preview
from src.email_notifications import generate_test_eml


def generate_previews(output_dir: Path) -> dict[str, Path]:
    """Generate HTML files and screenshots.
    
    Args:
        output_dir: Directory to save artifacts
    
    Returns:
        Dict mapping artifact names to file paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    
    # Render email with hosted URL (for browser preview)
    html_content, text_content = render_sample_email_for_preview(use_cid=False, screen=True)
    
    html_path = output_dir / "email_preview.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"Wrote HTML (hosted URL): {html_path}")
    artifacts["html"] = html_path
    
    text_path = output_dir / "email_preview.txt"
    text_path.write_text(text_content, encoding="utf-8")
    print(f"Wrote plain text: {text_path}")
    artifacts["text"] = text_path
    
    # Render email with CID reference (as sent)
    html_content_cid, _ = render_sample_email_for_preview(use_cid=True, screen=True)
    
    html_cid_path = output_dir / "email_preview_cid.html"
    html_cid_path.write_text(html_content_cid, encoding="utf-8")
    print(f"Wrote HTML (CID reference): {html_cid_path}")
    artifacts["html_cid"] = html_cid_path
    
    # Generate complete RFC822 .eml file
    eml_content, _ = generate_test_eml(
        recipient="krisc2004@gmail.com",
        subject="[TEST v4] New PM Jobs - Bubu Jobs",
    )
    
    eml_path = output_dir / "test_message.eml"
    eml_path.write_text(eml_content, encoding="utf-8")
    print(f"Wrote EML (RFC822): {eml_path}")
    artifacts["eml"] = eml_path
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            
            # Desktop screenshot
            desktop_page = browser.new_page(viewport={"width": 700, "height": 1200})
            desktop_page.set_content(html_content)
            desktop_page.wait_for_load_state("networkidle")
            desktop_screenshot = output_dir / "email_preview_desktop.png"
            desktop_page.screenshot(path=str(desktop_screenshot), full_page=True)
            print(f"Wrote desktop screenshot: {desktop_screenshot}")
            artifacts["desktop_png"] = desktop_screenshot
            desktop_page.close()
            
            # Mobile screenshot
            mobile_page = browser.new_page(viewport={"width": 375, "height": 812})
            mobile_page.set_content(html_content)
            mobile_page.wait_for_load_state("networkidle")
            mobile_screenshot = output_dir / "email_preview_mobile.png"
            mobile_page.screenshot(path=str(mobile_screenshot), full_page=True)
            print(f"Wrote mobile screenshot: {mobile_screenshot}")
            artifacts["mobile_png"] = mobile_screenshot
            mobile_page.close()
            
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
