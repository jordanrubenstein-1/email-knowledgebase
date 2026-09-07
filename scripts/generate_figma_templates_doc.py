#!/usr/bin/env python3
"""Generate the auto-briefed slice-structure reference in docs/figma-templates.md.

The Asana brief auto-builder reads its slice structures from the template dicts in
`scripts/create_calendar_tasks.py` (CZ_FIGMA_TEMPLATES, STF_FIGMA_TEMPLATES,
TI_FIGMA_TEMPLATES + kickers) — those dicts are the SINGLE SOURCE OF TRUTH.

This script renders those dicts into a marker-delimited, "do not edit by hand" block
in docs/figma-templates.md so humans/Claude have a browsable reference that can never
drift from what actually runs. Re-run it whenever the dicts change:

    uv run python scripts/generate_figma_templates_doc.py

CI/pre-commit can run it with --check to fail if the doc is stale.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Import the source-of-truth dicts from the auto-builder module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.create_calendar_tasks import (  # noqa: E402
    CZ_FIGMA_TEMPLATES, CZ_FIGMA_FILE_KEY,
    STF_FIGMA_TEMPLATES, STF_FIGMA_FILE_KEY, STF_KICKERS,
    TI_FIGMA_TEMPLATES, TI_FIGMA_FILE_KEY, TI_KICKERS,
)

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "figma-templates.md"
BEGIN = "<!-- BEGIN GENERATED: auto-briefed-slices (scripts/generate_figma_templates_doc.py) -->"
END = "<!-- END GENERATED: auto-briefed-slices -->"


def _node_url(node_id: str) -> str:
    return node_id.replace(":", "-")


def _cz_figma_url(node_id: str) -> str:
    return f"https://www.figma.com/design/{CZ_FIGMA_FILE_KEY}/2026-CZ-EDITORIALS?node-id={_node_url(node_id)}"


def _stf_figma_url(node_id: str) -> str:
    return (f"https://www.figma.com/design/{STF_FIGMA_FILE_KEY}"
            f"/St.-Frank-Templates-2026?node-id={_node_url(node_id)}&m=dev")


def _ti_figma_url(node_id: str) -> str:
    return f"https://www.figma.com/design/{TI_FIGMA_FILE_KEY}/TI-Templates?node-id={_node_url(node_id)}"


def _slice_layout(s: dict) -> str:
    """Layout for a structured (CZ/STF) slice: explicit `layout` key, else parsed from name."""
    if s.get("layout"):
        return s["layout"]
    name = s.get("name", "")
    if "50/50 left" in name:
        return "50/50 left"
    if "50/50 right" in name:
        return "50/50 right"
    return "Full width"


def _render_structured_template(key: str, t: dict, figma_url_fn) -> list[str]:
    """Render a CZ/STF-style template (structured `slices` list)."""
    lines: list[str] = []
    slices = t.get("slices", [])
    deliver = sum(1 for s in slices if s.get("type") == "image" and not s.get("optional"))
    lines.append(f"#### `{key}` — {t['name']} (`{t['node_id']}`)")
    lines.append("")
    if t.get("use_cases"):
        uc = t["use_cases"]
        uc_text = ", ".join(uc) if isinstance(uc, list) else str(uc)
        lines.append(f"- **Use for:** {uc_text}")
    if t.get("description"):
        lines.append(f"- **Description:** {t['description']}")
    lines.append(f"- **Figma:** {figma_url_fn(t['node_id'])}")
    lines.append(f"- **Slices to deliver (base, no sale banner):** {deliver}")
    if t.get("is_sale_hero"):
        lines.append("- **Sale hero:** the hero *is* the sale message — no sale banner is prepended.")
    lines.append("")
    for i, s in enumerate(slices, 1):
        flags = []
        if s.get("optional"):
            flags.append("optional")
        if s.get("no_visual"):
            flags.append("no visual direction")
        if s.get("type") == "brand_asset":
            flags.append("brand asset")
        flag_txt = f" _({', '.join(flags)})_" if flags else ""
        lines.append(f"{i}. **{s['name']}** — {_slice_layout(s)}{flag_txt}")
        for f in s.get("fields", []):
            lines.append(f"   - {f}")
    lines.append("")
    return lines


def _render_slices_text_template(key: str, t: dict, figma_url_fn) -> list[str]:
    """Render a TI-style template (pre-formatted `slices_text` string)."""
    lines: list[str] = []
    lines.append(f"#### `{key}` — {t['name']} (`{t['node_id']}`)")
    lines.append("")
    if t.get("use_cases"):
        uc = t["use_cases"]
        uc_text = ", ".join(uc) if isinstance(uc, list) else str(uc)
        lines.append(f"- **Use for:** {uc_text}")
    if t.get("description"):
        lines.append(f"- **Description:** {t['description']}")
    lines.append(f"- **Figma:** {figma_url_fn(t['node_id'])}")
    lines.append("")
    for raw in (t.get("slices_text", "") or "").split("\n"):
        if raw.strip():
            lines.append(f"    {raw.rstrip()}")
    lines.append("")
    return lines


def build_generated_block() -> str:
    out: list[str] = [BEGIN, ""]
    out.append("## Auto-Briefed Slice Structures — GENERATED (CZ / STF / TI)")
    out.append("")
    out.append("> **Do not edit by hand.** This section is generated from the template dicts in")
    out.append("> `scripts/create_calendar_tasks.py` by `scripts/generate_figma_templates_doc.py`.")
    out.append("> Those dicts are the source of truth the Asana brief auto-builder actually reads.")
    out.append("> Edit the dicts, then re-run the generator. Narrative rules (template selection,")
    out.append("> sale-banner behavior, historical caveats) live in CLAUDE.md, not here.")
    out.append("")

    # CZ
    out.append("### The Citizenry (CZ)")
    out.append("")
    out.append(f"File key `{CZ_FIGMA_FILE_KEY}`. Generator: `generate_cz_email_brief()`. "
               "Slices follow the 2026-06-05 consolidation rules (logo+hero and same-link adjacent "
               "slices merge). During a sale, a Slice 1 sale banner is prepended (all slices +1), a "
               "cycled kicker and a sale link-farm header slice are appended (see CLAUDE.md).")
    out.append("")
    for key, t in CZ_FIGMA_TEMPLATES.items():
        out.extend(_render_structured_template(key, t, _cz_figma_url))

    # STF
    out.append("### St. Frank (STF)")
    out.append("")
    out.append(f"File key `{STF_FIGMA_FILE_KEY}`. Generator: `generate_stf_email_brief()`. "
               "During a sale, a Slice 1 sale banner is prepended (all slices +1) EXCEPT the sale "
               "hero (`t7`). No kicker cycling or link-farm slice — kickers are manual (see below).")
    out.append("")
    for key, t in STF_FIGMA_TEMPLATES.items():
        out.extend(_render_structured_template(key, t, _stf_figma_url))
    out.append("**STF standalone kickers / category blocks** (manual add-ons; not auto-attached):")
    out.append("")
    for key, k in STF_KICKERS.items():
        out.append(f"- `{key}` — **{k['name']}** (`{k['node_id']}`) — {k['layout']} — {k['description']}")
    out.append("")

    # TI
    out.append("### The Inside (TI)")
    out.append("")
    out.append(f"File key `{TI_FIGMA_FILE_KEY}`. Generator: `generate_ti_email_brief()`. "
               "Slices are authored as pre-formatted text per template. During a sale, a Slice 1 "
               "sale banner is prepended via the prompt; kickers are selected by `pick_ti_kicker()`.")
    out.append("")
    for key, t in TI_FIGMA_TEMPLATES.items():
        out.extend(_render_slices_text_template(key, t, _ti_figma_url))
    out.append("**TI kickers** (selected by `pick_ti_kicker()`):")
    out.append("")
    for key, k in TI_KICKERS.items():
        out.append(f"#### `{key}` — {k['name']} (`{k['node_id']}`)")
        out.append("")
        for raw in (k.get("slices_text", "") or "").split("\n"):
            if raw.strip():
                out.append(f"    {raw.rstrip()}")
        out.append("")

    out.append(END)
    return "\n".join(out).rstrip() + "\n"


def splice(doc_text: str, block: str) -> str:
    if BEGIN in doc_text and END in doc_text:
        pre = doc_text.split(BEGIN, 1)[0].rstrip("\n")
        post = doc_text.split(END, 1)[1].lstrip("\n")
        parts = [pre, "", block]
        if post.strip():
            parts += ["", post]
        return "\n".join(parts).rstrip() + "\n"
    # No markers yet — append at end.
    return doc_text.rstrip("\n") + "\n\n---\n\n" + block


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="Exit non-zero if docs/figma-templates.md is out of date (do not write).")
    args = ap.parse_args()

    block = build_generated_block()
    current = DOC_PATH.read_text() if DOC_PATH.exists() else ""
    updated = splice(current, block)

    if args.check:
        if current != updated:
            print("docs/figma-templates.md is STALE — run: uv run python scripts/generate_figma_templates_doc.py")
            return 1
        print("docs/figma-templates.md is up to date.")
        return 0

    DOC_PATH.write_text(updated)
    print(f"Wrote generated slice block to {DOC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
