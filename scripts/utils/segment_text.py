"""Shared helpers for resolving TI's "Segment (Text)" Asana field into a Klaviyo
audience. See CLAUDE.md's "TI Segment (Text) field" section for the 4 accepted
values and the send-cadence rules that decide which one a task gets.
"""

from __future__ import annotations

import re


def normalize_segment_key(raw: str) -> str:
    """Lowercase, strip everything but letters/digits — same normalization
    ID's build_pt_campaign.py uses for Segment (Text), duplicated here rather
    than cross-imported to keep the Klaviyo and Braze automation paths independent."""
    return re.sub(r"[^a-z0-9]+", "", (raw or "").strip().lower())


TI_SEGMENT_TEXT_KEY_MAP = {
    "fullfile": "full_file",
    "allfullfile": "full_file",
    "all": "full_file",
    "engaged": "engaged",
    "swatchpurchasers": "swatch_purchasers",
    "swatchnonpurchasers": "swatch_non_purchasers",
    "swatchnonpurchaser": "swatch_non_purchasers",
}

# Swatch Purchasers/Non-Purchasers Klaviyo segments were created 2026-08-11, but
# per Jordan, only take effect for sends on/after this date — same rationale as
# ID's _ID_SEGMENTATION_V2_CUTOFF: protects tasks briefed before the segments
# existed from being silently redirected to them.
TI_SWATCH_SEGMENTATION_CUTOFF = "2026-08-18"


def resolve_ti_segment_key(raw: str, default: str = "engaged", send_date: str | None = None) -> str:
    """Map a TI Segment (Text) value to a brand_config.yaml audiences key.

    Defaults to "engaged" (TI's baseline send list), not "full_file" — the
    opposite default from ID, per the ticket's cadence rules: Engaged gets
    every regular send, Full File is the restricted 1-2x/week tier.

    `send_date` (Asana due_on, "YYYY-MM-DD") gates the two swatch keys: before
    TI_SWATCH_SEGMENTATION_CUTOFF (or when the date is unknown), they fall back
    to "engaged" instead.
    """
    key = normalize_segment_key(raw)
    resolved = TI_SEGMENT_TEXT_KEY_MAP.get(key, default)
    if resolved in ("swatch_purchasers", "swatch_non_purchasers"):
        if not send_date or send_date < TI_SWATCH_SEGMENTATION_CUTOFF:
            return "engaged"
    return resolved


def resolve_audience_names(cfg: dict, seg_key: str) -> tuple[list[str], list[str]]:
    """Given a brand cfg dict + resolved audiences key, return (included, excluded)
    Klaviyo list/segment name strings.

    Falls back to the brand's flat klaviyo.audiences.included when the key has
    no audiences_cfg entry.
    """
    audiences_cfg = cfg.get("audiences", {})
    klaviyo_cfg = cfg.get("klaviyo", {}).get("audiences", {})
    seg_info = audiences_cfg.get(seg_key, {})
    if seg_info:
        included = list(seg_info["segments"]) if "segments" in seg_info else [seg_info.get("segment", "")]
    else:
        included = klaviyo_cfg.get("included", [])
    excluded = klaviyo_cfg.get("excluded", [])
    return [n for n in included if n], [n for n in excluded if n]
