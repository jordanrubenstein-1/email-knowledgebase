"""
Interior Define email component builder.

Usage:
    from scripts.build_id_email import build_email

    html = build_email(
        preheader="Your cart is waiting — up to 30% off.",
        blocks=[
            {"block": "logo_bar"},
            {"block": "hero_full", "image_url": "https://...", "headline": "...", ...},
            {"block": "category_nav", "preset": "default_light", "categories": [...]},
            {"block": "feature_text_image", "preset": "white", "title": "...", "body": "..."},
            {"block": "header_with_cta", "preset": "default_dark", "header": "...", ...},
            {"block": "footer"},
        ],
    )

    with open("scripts/email_previews/my_email.html", "w") as f:
        f.write(html)
"""

import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, Undefined

BLOCKS_DIR = Path(__file__).parent.parent / "components" / "id" / "blocks"

# Color presets — choose one via `preset` key in a block config.
# All colors are inline-style safe hex strings.
PRESETS = {
    "default_dark": {
        "bg": "#21363e",
        "text": "#ffffff",
        "subtext": "#ffffff",
        "btn_bg": "#fffffe",
        "btn_text": "#000000",
    },
    "default_light": {
        "bg": "#f7f3eb",
        "text": "#676565",
        "subtext": "#676565",
        "btn_bg": "#21363e",
        "btn_text": "#ffffff",
    },
    "white": {
        "bg": "#fffffe",
        "text": "#676564",
        "subtext": "#777777",
        "btn_bg": "#21363e",
        "btn_text": "#ffffff",
    },
    "tan": {
        "bg": "#f7f3eb",
        "text": "#676564",
        "subtext": "#777777",
        "btn_bg": "#21363e",
        "btn_text": "#ffffff",
    },
}


def resolve_colors(block_config: dict) -> dict:
    """Return colors dict from preset name, inline colors dict, or default (white)."""
    if "colors" in block_config:
        # Caller provided explicit hex values — wins over preset.
        return block_config["colors"]
    preset_name = block_config.get("preset", "white")
    if preset_name not in PRESETS:
        raise ValueError(
            f"Unknown preset '{preset_name}'. Choose from: {list(PRESETS.keys())} or pass colors={{...}} directly."
        )
    return PRESETS[preset_name]


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(BLOCKS_DIR)),
        undefined=Undefined,
        autoescape=False,
    )


def _render_block(env: Environment, block_config: dict) -> str:
    block_name = block_config["block"]
    template_file = f"{block_name}.html"
    try:
        tmpl = env.get_template(template_file)
    except Exception as e:
        raise FileNotFoundError(
            f"Block template '{template_file}' not found in {BLOCKS_DIR}. "
            f"Available blocks: {[f.name for f in BLOCKS_DIR.glob('*.html') if f.name != 'email_shell.html']}"
        ) from e

    colors = resolve_colors(block_config)
    ctx = {k: v for k, v in block_config.items() if k not in ("block", "preset", "colors")}
    ctx["colors"] = colors
    return tmpl.render(**ctx)


def build_email(preheader: str, blocks: list[dict], title: str = "Interior Define") -> str:
    """
    Render a complete email HTML string from a list of block configs.

    Args:
        preheader: Hidden preview text shown in inbox (50–90 chars).
        blocks: List of block config dicts. Each must have a "block" key
                matching a template filename in components/id/blocks/.
        title: Optional <title> tag value.

    Returns:
        Full HTML string ready to preview in a browser or paste into Braze.
    """
    env = _make_env()

    body_parts = []
    for block_config in blocks:
        body_parts.append(_render_block(env, block_config))

    body_content = "\n".join(body_parts)

    shell_tmpl = env.get_template("email_shell.html")
    return shell_tmpl.render(
        preheader=preheader,
        title=title,
        body_content=body_content,
    )
