"""
check_activity.py — summarize auto-built and auto-QA'd campaigns from the webhook log.

Usage:
  uv run python scripts/braze_automation/check_activity.py            # today
  uv run python scripts/braze_automation/check_activity.py --days 3   # last 3 days
  uv run python scripts/braze_automation/check_activity.py --date 2026-07-06
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_FILE = Path("/private/tmp/webhook-server.log")
ASANA_TASK_URL = "https://app.asana.com/0/1207522423363072/{gid}"

# ── regex patterns ────────────────────────────────────────────────────────────

# Timestamp at line start
_TS = r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2},\d+"

# Build completions
_BUILD_PT   = re.compile(_TS + r".*PT Email build complete: (.+?) → Ready for QA \((.+?)\)")
_BUILD_SMS  = re.compile(_TS + r".*SMS build complete: (.+?) \(gid=(\d+)\)")
_BUILD_PUSH = re.compile(_TS + r".*Push.*build complete.*?(\[.+?\].+?)(?:\s*\(gid=(\d+))?")

# QA completion summary line (always present)
# Use a greedy label match up to the last colon-separated check summary
_QA_SUMMARY = re.compile(_TS + r".*QA complete for (.+): ((?:send_time|segment|filters|test_send)=.+)")

# QA run — gives us task GID and campaign name
_QA_RUN     = re.compile(_TS + r".*QA run: brand=(\w+), campaign=([0-9a-f]+), channel=(\w+)")
_QA_COMMENT = re.compile(_TS + r".*Posted QA comment on task (\d+) \((\d+) issue")
_QA_CAMP_NAME = re.compile(_TS + r".*Campaign name \(from Braze URL\): '(.+?)'")

# Individual QA check results
_QA_CHECK_PASS = re.compile(r"✓ (.+)")
_QA_CHECK_FAIL = re.compile(r"✗|WARNING.*not found|WARNING.*Expected")
_QA_WARNING    = re.compile(_TS + r".*qa_designed_email.*WARNING - (.+)")


def _send_date_from_campaign_name(name: str) -> str:
    """Extract send date from campaign name, e.g. P_EM_2026_07_12_... → 2026-07-12."""
    m = re.search(r"_(\d{4})_(\d{2})_(\d{2})_", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def parse_log(log_path: Path, date_prefixes: list[str]) -> dict:
    """
    Parse the log file and return a dict keyed by task GID with build/QA info.
    date_prefixes: list of 'YYYY-MM-DD' strings to include.
    """
    lines = log_path.read_text(errors="replace").splitlines()

    # We'll collect events by a session key (task GID when known, else campaign id)
    # Use two passes: first collect all raw events, then assemble per-task records.

    builds: dict[str, dict] = {}   # gid → build record
    qa_sessions: list[dict] = []   # ordered list of QA sessions

    current_qa: dict | None = None

    for line in lines:
        # Filter to requested dates
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", line)
        if not date_match or date_match.group(1) not in date_prefixes:
            continue

        ts = date_match.group(1)

        # ── Build events ─────────────────────────────────────────────────────
        m = _BUILD_PT.search(line)
        if m:
            label = m.group(2).strip()
            url   = m.group(3).strip()
            # Extract GID from Asana writeback line nearby — but we may not have
            # it here; we'll correlate via QA run later. Use campaign URL as key.
            camp_id = re.search(r"/campaigns/([0-9a-f]+)/", url)
            key = camp_id.group(1) if camp_id else label
            builds[key] = {
                "type": "PT Email",
                "label": label,
                "braze_url": url,
                "date": ts,
                "gid": None,
            }
            continue

        m = _BUILD_SMS.search(line)
        if m:
            label = m.group(2).strip()
            gid   = m.group(3)
            builds[gid] = {
                "type": "SMS",
                "label": label,
                "braze_url": None,
                "date": ts,
                "gid": gid,
            }
            continue

        # ── QA run start ──────────────────────────────────────────────────────
        m = _QA_RUN.search(line)
        if m:
            current_qa = {
                "date": ts,
                "brand": m.group(2),
                "campaign_id": m.group(3),
                "channel": m.group(4),
                "label": None,
                "campaign_name": None,
                "gid": None,
                "issues": [],
                "warnings": [],
                "summary": None,
            }
            continue

        if current_qa is None:
            continue

        # ── Campaign name ─────────────────────────────────────────────────────
        m = _QA_CAMP_NAME.search(line)
        if m:
            current_qa["campaign_name"] = m.group(2)
            continue

        # ── Warning line ──────────────────────────────────────────────────────
        m = _QA_WARNING.search(line)
        if m:
            current_qa["warnings"].append(m.group(2).strip())
            continue

        # ── Posted QA comment (gives task GID + issue count) ──────────────────
        m = _QA_COMMENT.search(line)
        if m:
            current_qa["gid"]    = m.group(2)
            current_qa["n_issues"] = int(m.group(3))
            continue

        # ── QA summary line ───────────────────────────────────────────────────
        m = _QA_SUMMARY.search(line)
        if m:
            if current_qa is not None:
                current_qa["label"]   = m.group(2).strip()
                current_qa["summary"] = m.group(3).strip()
                qa_sessions.append(current_qa)
                current_qa = None
            continue

    return {"builds": builds, "qa_sessions": qa_sessions}


def _check_symbol(summary: str, key: str) -> str:
    """Extract pass/fail symbol for a key like 'send_time' from summary string."""
    m = re.search(rf"{key}=([✓✗])", summary)
    return m.group(1) if m else "?"


def render(data: dict, date_prefixes: list[str]) -> str:
    builds = data["builds"]
    qa_sessions = data["qa_sessions"]

    lines = []
    label_width = 50

    # ── Builds ────────────────────────────────────────────────────────────────
    # Correlate build GIDs from QA sessions (QA always follows a build)
    build_campaign_to_gid: dict[str, str] = {}
    for qa in qa_sessions:
        if qa["gid"] and qa["campaign_id"]:
            build_campaign_to_gid[qa["campaign_id"]] = qa["gid"]

    auto_built = []
    for key, b in builds.items():
        gid = b["gid"] or build_campaign_to_gid.get(key)
        # Try to extract send date from campaign name in braze_url first, then label
        url_camp = ""
        if b.get("braze_url"):
            m = re.search(r"campaignName=([^&]+)", b["braze_url"])
            if m:
                url_camp = m.group(1)
        camp_name = url_camp or b["label"]
        send_date = _send_date_from_campaign_name(camp_name)
        asana_url = ASANA_TASK_URL.format(gid=gid) if gid else "(GID unknown)"
        auto_built.append({
            "date": b["date"],
            "label": b["label"],
            "type": b["type"],
            "send_date": send_date,
            "asana_url": asana_url,
            "braze_url": b.get("braze_url"),
        })

    if auto_built:
        lines.append("## Auto-Built\n")
        for b in sorted(auto_built, key=lambda x: x["date"]):
            lines.append(f"**{b['label']}** ({b['type']})")
            if b["send_date"]:
                lines.append(f"  Send date : {b['send_date']}")
            lines.append(f"  Built at  : {b['date']}")
            lines.append(f"  Asana     : {b['asana_url']}")
            if b["braze_url"]:
                lines.append(f"  Braze     : {b['braze_url']}")
            lines.append("")

    # ── QA'd ─────────────────────────────────────────────────────────────────
    if qa_sessions:
        lines.append("## Auto-QA'd\n")
        for qa in sorted(qa_sessions, key=lambda x: x["date"]):
            label     = qa["label"] or qa["campaign_name"] or "(unknown)"
            gid       = qa["gid"]
            asana_url = ASANA_TASK_URL.format(gid=gid) if gid else "(GID unknown)"
            camp_name = qa["campaign_name"] or ""
            send_date = _send_date_from_campaign_name(camp_name)
            summary   = qa.get("summary", "")
            n_issues  = qa.get("n_issues", 0)

            status = "✓ All passed" if n_issues == 0 else f"⚠ {n_issues} issue(s)"

            lines.append(f"**{label}**")
            if send_date:
                lines.append(f"  Send date : {send_date}")
            lines.append(f"  QA'd at   : {qa['date']}")
            lines.append(f"  Asana     : {asana_url}")
            lines.append(f"  Result    : {status}")

            if summary:
                checks = {
                    "send_time": "Send time",
                    "segment":   "Segment",
                    "filters":   "Filters",
                    "test_send": "Test send",
                }
                check_parts = []
                for key, label_str in checks.items():
                    sym = _check_symbol(summary, key)
                    if sym == "✗":
                        check_parts.append(f"{label_str} ✗")
                if check_parts:
                    lines.append(f"  Checks    : {', '.join(check_parts)} failed")

            for w in qa.get("warnings", []):
                lines.append(f"  ⚠ {w}")

            lines.append("")

    if not auto_built and not qa_sessions:
        date_str = ", ".join(date_prefixes)
        lines.append(f"Nothing auto-built or auto-QA'd on {date_str}.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Summarize auto-build/QA activity")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Specific date YYYY-MM-DD (default: today)")
    group.add_argument("--days", type=int, default=1, help="Last N days (default: 1 = today)")
    args = parser.parse_args()

    if args.date:
        date_prefixes = [args.date]
    else:
        today = date.today()
        date_prefixes = [
            (today - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)
        ]

    if not LOG_FILE.exists():
        print(f"Log file not found: {LOG_FILE}", file=sys.stderr)
        sys.exit(1)

    data   = parse_log(LOG_FILE, date_prefixes)
    output = render(data, date_prefixes)
    print(output)


if __name__ == "__main__":
    main()
