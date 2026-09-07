#!/usr/bin/env python3
"""
Unified QA checker for email and SMS campaigns.

Orchestrates config validation (validate_campaign_config.py) and
HTML-level validation (validate_html.py) into a single CLI tool.

Usage:
    # Validate a campaign config YAML
    uv run python scripts/qa_check.py --config path/to/config.yaml

    # Validate HTML content for a brand
    uv run python scripts/qa_check.py --html campaigns/html/some_email.html \\
        --brand HAV --subscription-group Marketing

    # Full validation (config + HTML)
    uv run python scripts/qa_check.py --config path/to/config.yaml \\
        --html campaigns/html/some_email.html

    # Include network checks (link resolution, image size)
    uv run python scripts/qa_check.py --html campaigns/html/some_email.html \\
        --brand HAV --check-links

    # Batch: validate all HTML files matching a glob
    uv run python scripts/qa_check.py --html-dir campaigns/html/ \\
        --brand HAV --subscription-group Marketing

    # JSON output (for automation)
    uv run python scripts/qa_check.py --html campaigns/html/some_email.html \\
        --brand HAV --json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from validate_html import validate_html, validate_sms
from validate_campaign_config import validate_campaign_config, BRAND_DOMAINS

# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------

_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _colour(text: str, code: str) -> str:
    """Wrap text in ANSI colour if stdout is a terminal."""
    if sys.stdout.isatty():
        return f"{code}{text}{_RESET}"
    return text


# ---------------------------------------------------------------------------
# Result dataclass-like dict
# ---------------------------------------------------------------------------

def _make_result(
    source: str,
    errors: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    return {
        "source": source,
        "errors": errors,
        "warnings": warnings,
        "passed": len(errors) == 0,
    }


# ---------------------------------------------------------------------------
# Config validation wrapper
# ---------------------------------------------------------------------------

def run_config_validation(config_path: str) -> Dict[str, Any]:
    """Load a campaign config YAML and validate it.

    Returns a result dict with errors and warnings.
    """
    import yaml

    path = Path(config_path)
    if not path.exists():
        return _make_result(str(path), [f"Config file not found: {path}"], [])

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        return _make_result(str(path), [f"Error loading YAML: {e}"], [])

    is_valid, errors, _dt, warnings = validate_campaign_config(config)
    return _make_result(str(path), errors, warnings)


# ---------------------------------------------------------------------------
# HTML validation wrapper
# ---------------------------------------------------------------------------

def run_html_validation(
    html_path: str,
    brand: str,
    channel: str = "email",
    subscription_group: str = "Marketing",
    check_links: bool = False,
) -> Dict[str, Any]:
    """Load an HTML file and run all HTML QA checks.

    Returns a result dict with errors and warnings.
    """
    path = Path(html_path)
    if not path.exists():
        return _make_result(str(path), [f"HTML file not found: {path}"], [])

    try:
        html_content = path.read_text(encoding="utf-8")
    except Exception as e:
        return _make_result(str(path), [f"Error reading HTML: {e}"], [])

    errors, warnings = validate_html(
        html_content=html_content,
        brand=brand,
        channel=channel,
        subscription_group=subscription_group,
        check_links=check_links,
    )
    return _make_result(str(path), errors, warnings)


# ---------------------------------------------------------------------------
# SMS validation wrapper
# ---------------------------------------------------------------------------

def run_sms_validation(
    sms_body: str,
    brand: str,
) -> Dict[str, Any]:
    """Validate an SMS message body.

    Returns a result dict with errors and warnings.
    """
    errors, warnings = validate_sms(sms_body, brand)
    return _make_result("<sms body>", errors, warnings)


# ---------------------------------------------------------------------------
# Unified runner (for programmatic use from builders)
# ---------------------------------------------------------------------------

def run_qa_checks(
    config: Optional[Dict[str, Any]] = None,
    html_content: Optional[str] = None,
    brand: Optional[str] = None,
    channel: str = "email",
    subscription_group: str = "Marketing",
    sms_body: Optional[str] = None,
    check_links: bool = False,
) -> Dict[str, Any]:
    """Run all applicable QA checks and return a combined result.

    Args:
        config: Campaign config dict (optional).
        html_content: Email HTML string (optional).
        brand: Brand code — required for HTML/SMS checks.
        channel: "email" or "sms".
        subscription_group: "Marketing" or "Transactional".
        sms_body: SMS body text (optional, for SMS campaigns).
        check_links: Enable network-dependent checks.

    Returns:
        Combined result dict with config_result, html_result, sms_result,
        plus top-level errors/warnings/passed.
    """
    results: Dict[str, Any] = {
        "config_result": None,
        "html_result": None,
        "sms_result": None,
        "errors": [],
        "warnings": [],
        "passed": True,
    }

    # Config validation
    if config is not None:
        is_valid, errors, _dt, warnings = validate_campaign_config(config)
        result = _make_result("<config>", errors, warnings)
        results["config_result"] = result
        results["errors"].extend(errors)
        results["warnings"].extend(warnings)
        if not result["passed"]:
            results["passed"] = False

    # HTML validation
    if html_content is not None and brand:
        errors, warnings = validate_html(
            html_content=html_content,
            brand=brand,
            channel=channel,
            subscription_group=subscription_group,
            check_links=check_links,
        )
        result = _make_result("<html>", errors, warnings)
        results["html_result"] = result
        results["errors"].extend(errors)
        results["warnings"].extend(warnings)
        if not result["passed"]:
            results["passed"] = False

    # SMS validation
    if sms_body is not None and brand:
        errors, warnings = validate_sms(sms_body, brand)
        result = _make_result("<sms>", errors, warnings)
        results["sms_result"] = result
        results["errors"].extend(errors)
        results["warnings"].extend(warnings)
        if not result["passed"]:
            results["passed"] = False

    return results


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_result(result: Dict[str, Any]) -> None:
    """Pretty-print a single validation result to the terminal."""
    source = result["source"]
    print(f"\n{_colour(f'=== {source} ===', _BOLD)}")

    if result["passed"] and not result["warnings"]:
        print(_colour("  PASSED — no issues found.", _GREEN))
        return

    if result["errors"]:
        print(_colour(f"  ERRORS ({len(result['errors'])}):", _RED))
        for err in result["errors"]:
            print(f"    {_colour('ERROR', _RED)}: {err}")

    if result["warnings"]:
        print(_colour(f"  WARNINGS ({len(result['warnings'])}):", _YELLOW))
        for warn in result["warnings"]:
            print(f"    {_colour('WARN', _YELLOW)}: {warn}")

    if result["passed"]:
        print(_colour("  RESULT: PASSED (with warnings)", _GREEN))
    else:
        print(_colour("  RESULT: FAILED", _RED))


def _print_summary(results: List[Dict[str, Any]]) -> None:
    """Print a summary across multiple file results."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    total_errors = sum(len(r["errors"]) for r in results)
    total_warnings = sum(len(r["warnings"]) for r in results)

    print(f"\n{_colour('=' * 60, _BOLD)}")
    print(f"{_colour('QA SUMMARY', _BOLD)}")
    print(f"{_colour('=' * 60, _BOLD)}")
    print(f"  Files checked: {total}")
    print(f"  Passed:        {_colour(str(passed), _GREEN)}")
    if failed:
        print(f"  Failed:        {_colour(str(failed), _RED)}")
    else:
        print(f"  Failed:        {failed}")
    print(f"  Total errors:  {total_errors}")
    print(f"  Total warnings: {total_warnings}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run QA checks on email/SMS campaign content.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--config",
        help="Path to a campaign config YAML file.",
    )
    parser.add_argument(
        "--html",
        help="Path to an email HTML file.",
    )
    parser.add_argument(
        "--html-dir",
        help="Directory of HTML files to batch-validate.",
    )
    parser.add_argument(
        "--brand",
        choices=list(BRAND_DOMAINS.keys()),
        help="Brand code (required for HTML validation).",
    )
    parser.add_argument(
        "--channel",
        choices=["email", "sms"],
        default="email",
        help="Channel (default: email).",
    )
    parser.add_argument(
        "--subscription-group",
        choices=["Marketing", "Transactional"],
        default="Marketing",
        help="Subscription group (default: Marketing).",
    )
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="Enable network checks (HTTP HEAD for links and images).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON.",
    )

    args = parser.parse_args()

    if not args.config and not args.html and not args.html_dir:
        parser.error("At least one of --config, --html, or --html-dir is required.")

    if (args.html or args.html_dir) and not args.brand:
        parser.error("--brand is required when validating HTML files.")

    results: List[Dict[str, Any]] = []

    # Config validation
    if args.config:
        result = run_config_validation(args.config)
        results.append(result)

    # Single HTML file
    if args.html:
        result = run_html_validation(
            html_path=args.html,
            brand=args.brand,
            channel=args.channel,
            subscription_group=args.subscription_group,
            check_links=args.check_links,
        )
        results.append(result)

    # Batch HTML directory
    if args.html_dir:
        html_dir = Path(args.html_dir)
        if not html_dir.is_dir():
            print(f"Error: {html_dir} is not a directory.", file=sys.stderr)
            return 1

        html_files = sorted(html_dir.glob("*.html"))
        if not html_files:
            print(f"No .html files found in {html_dir}.", file=sys.stderr)
            return 1

        print(f"Checking {len(html_files)} HTML files in {html_dir}...")

        for html_file in html_files:
            result = run_html_validation(
                html_path=str(html_file),
                brand=args.brand,
                channel=args.channel,
                subscription_group=args.subscription_group,
                check_links=args.check_links,
            )
            results.append(result)

    # Output
    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            _print_result(result)
        if len(results) > 1:
            _print_summary(results)

    # Exit code: 1 if any errors, 0 otherwise
    has_errors = any(not r["passed"] for r in results)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
