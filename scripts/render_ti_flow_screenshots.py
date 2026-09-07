"""
Render screenshots for TI Klaviyo flow email steps.

Reads the specified YAML files, finds their HTML, preprocesses Liquid
(evaluating time-based conditionals with today's date so the correct
banner branch is shown), then renders PNGs using Playwright at 1x scale.

Saves to campaigns/screenshots/ and updates the YAML screenshot field.

Usage:
    uv run python scripts/render_ti_flow_screenshots.py
    uv run python scripts/render_ti_flow_screenshots.py --dry-run
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CAMPAIGNS = ROOT / "campaigns"
HTML_DIR = CAMPAIGNS / "html"
SCREENSHOTS_DIR = CAMPAIGNS / "screenshots"

# featured steps: flow canvas_name → sequence_positions to render
# Welcome Series uses T27-T31 (the live V2 steps as of 2026-03-02)
FEATURE_STEPS = {
    "Welcome Series - NEW":                              [27, 28, 29, 30, 31],
    "Abandon: Cart Abandon NONSWATCH":                   [1, 2],
    "[NEW] Order Placed: NONSWATCH Order Confirmation Email": [1],
    "[NEW] Shipped: NONSWATCH Order Shipped":            [1, 2],  # only 2 live T1 variants
    "[NEW] Order Delivered: NONSWATCH Post Purchase Flow (AfterShip)": [1, 2, 3, 4],
    "Shipped: Order Shipped SWATCH":                     [2, 1, 6, 4, 5],  # T1,T2,T3,T4,T5 (3=draft skip)
    "Confirmation: SWATCH Order Placed":                 [1],
    "Delayed Order":                                     [1, 2, 3],
    "[TRADE] Swatch Order -- SHIPPED":                   [5, 1, 2, 3, 4],  # T1=seq5, T2-T5=seq1-4
    "Waitlist: Your item is back in stock.":             [1],
    "Waitlist: Added to Waitlist":                       [1],
}


def _eval_now_condition(cond: str, now: datetime) -> bool:
    """Evaluate a Liquid 'now >= "..." and now < "..."' condition using real time."""
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    # Extract all datetime strings from the condition
    parts = re.findall(r'"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"', cond)
    result = True
    for dt_str in parts:
        if ">=" in cond.split(dt_str)[0].rsplit("now", 1)[-1]:
            result = result and (now_str >= dt_str)
        elif "<" in cond.split(dt_str)[0].rsplit("now", 1)[-1]:
            result = result and (now_str < dt_str)
    return result


def preprocess_liquid(html: str) -> str:
    """
    Strip/evaluate Liquid tags so Playwright renders a realistic preview.

    - Time-based {% if now >= "..." %} conditions are evaluated using today's
      date — the branch that would actually send today is kept.
    - All other {% if %}...{% endif %} blocks keep the first (if) branch,
      matching the behaviour of render_liquid_preview.preprocess_html step 7.
    - Remaining {% ... %} tags and {{ ... }} expressions are stripped.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def pick_branch(m: re.Match) -> str:
        block = m.group(0)
        # Extract condition from opening {% if ... %}
        cond_match = re.match(r'\{%-?\s*if\s+(.+?)\s*-?%\}', block, re.DOTALL)
        cond = cond_match.group(1) if cond_match else ""

        # Strip the opening {% if %} and closing {% endif %}
        body = re.sub(r'^\{%-?\s*if[^%]+%\}', '', block)
        body = re.sub(r'\{%-?\s*endif\s*-?%\}$', '', body)

        branches = re.split(r'\{%-?\s*else(?:if[^%]*)?\s*-?%\}', body)
        if_branch = branches[0]
        else_branch = branches[1] if len(branches) > 1 else ""

        if "now" in cond and re.search(r'\d{4}-\d{2}-\d{2}', cond):
            return if_branch if _eval_now_condition(cond, now) else else_branch
        return if_branch  # default: keep if branch for non-time conditions

    # Evaluate / strip all {% if %}...{% endif %} blocks
    html = re.sub(
        r'\{%-?\s*if[^%]+%\}.*?\{%-?\s*endif\s*-?%\}',
        pick_branch,
        html,
        flags=re.DOTALL,
    )

    # Strip remaining Liquid tags and expressions
    html = re.sub(r'\{%-?.*?-?%\}', '', html, flags=re.DOTALL)
    html = re.sub(r'\{\{.*?\}\}', '', html, flags=re.DOTALL)
    return html


def find_target_yamls() -> list[dict]:
    targets = []
    for yaml_file in sorted(CAMPAIGNS.glob("klv-flow-*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or data.get("brand") != "TI":
            continue
        canvas_name = data.get("canvas_name", "")
        seq = data.get("sequence_position", 0)
        if canvas_name not in FEATURE_STEPS:
            continue
        if seq not in FEATURE_STEPS[canvas_name]:
            continue
        send = (data.get("sends") or [{}])[0]
        html_ref = send.get("html_file", "")
        if not html_ref:
            print(f"  !! No html_file in: {yaml_file.name}")
            continue
        html_path = CAMPAIGNS / html_ref
        if not html_path.exists():
            print(f"  !! HTML missing: {html_path}")
            continue
        screenshot_name = yaml_file.stem + ".png"
        screenshot_path = SCREENSHOTS_DIR / screenshot_name
        targets.append({
            "yaml_file": yaml_file,
            "data": data,
            "html_path": html_path,
            "screenshot_path": screenshot_path,
            "screenshot_name": screenshot_name,
            "canvas_name": canvas_name,
            "seq": seq,
        })
    return targets


def capture_screenshot(html_content: str, output_path: Path, browser, width: int = 600) -> bool:
    try:
        context = browser.new_context(
            viewport={"width": width, "height": 800},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.set_content(html_content, wait_until="networkidle")
        height = page.evaluate("document.body.scrollHeight")
        page.set_viewport_size({"width": width, "height": min(height, 5000)})
        page.screenshot(path=str(output_path), full_page=True)
        context.close()
        return True
    except Exception as e:
        print(f"  Screenshot error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    SCREENSHOTS_DIR.mkdir(exist_ok=True)

    targets = find_target_yamls()
    print(f"Found {len(targets)} TI flow steps to render")

    already = [t for t in targets if t["screenshot_path"].exists()]
    to_render = [t for t in targets if not t["screenshot_path"].exists()]
    print(f"  Already rendered: {len(already)}")
    print(f"  Need rendering:   {len(to_render)}")

    if args.dry_run or not to_render:
        if args.dry_run:
            for t in to_render:
                print(f"  [DRY] T{t['seq']:02d} {t['canvas_name'][:50]}  → {t['screenshot_name']}")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run: uv add playwright && uv run playwright install chromium")
        sys.exit(1)

    saved, failed = 0, 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for t in to_render:
            raw_html = t["html_path"].read_text(encoding="utf-8", errors="replace")
            html_content = preprocess_liquid(raw_html)
            print(f"  Rendering T{t['seq']:02d} {t['canvas_name'][:50]}…", end=" ", flush=True)
            ok = capture_screenshot(html_content, t["screenshot_path"], browser)
            if ok:
                for send in t["data"].get("sends", []):
                    if send.get("channel") == "email":
                        send["screenshot"] = f"screenshots/{t['screenshot_name']}"
                        break
                with open(t["yaml_file"], "w") as f:
                    yaml.dump(t["data"], f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                print("✓")
                saved += 1
            else:
                print("✗")
                failed += 1
        browser.close()

    print(f"\nDone: {saved} saved, {failed} failed")


if __name__ == "__main__":
    main()
