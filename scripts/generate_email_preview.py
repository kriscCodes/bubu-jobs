#!/usr/bin/env python3
"""Generate email preview artifacts (HTML file and screenshots).

This script renders the sample email to HTML and captures screenshots
at desktop and mobile widths for design review.

Usage:
    python scripts/generate_email_preview.py [--output-dir /path/to/output]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.html_email import render_sample_email_for_preview


def generate_previews(output_dir: Path) -> dict[str, Path]:
    """Generate HTML file and screenshots.
    
    Args:
        output_dir: Directory to save artifacts
    
    Returns:
        Dict mapping artifact names to file paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    html_content, text_content = render_sample_email_for_preview()
    
    html_path = output_dir / "email_preview.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"Wrote HTML: {html_path}")
    
    text_path = output_dir / "email_preview.txt"
    text_path.write_text(text_content, encoding="utf-8")
    print(f"Wrote plain text: {text_path}")
    
    artifacts = {
        "html": html_path,
        "text": text_path,
    }
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch()
            
            desktop_page = browser.new_page(viewport={"width": 800, "height": 1200})
            desktop_page.set_content(html_content)
            desktop_page.wait_for_load_state("networkidle")
            desktop_screenshot = output_dir / "email_preview_desktop.png"
            desktop_page.screenshot(path=str(desktop_screenshot), full_page=True)
            print(f"Wrote desktop screenshot: {desktop_screenshot}")
            artifacts["desktop_png"] = desktop_screenshot
            
            mobile_page = browser.new_page(viewport={"width": 375, "height": 812})
            mobile_page.set_content(html_content)
            mobile_page.wait_for_load_state("networkidle")
            mobile_screenshot = output_dir / "email_preview_mobile.png"
            mobile_page.screenshot(path=str(mobile_screenshot), full_page=True)
            print(f"Wrote mobile screenshot: {mobile_screenshot}")
            artifacts["mobile_png"] = mobile_screenshot
            
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
