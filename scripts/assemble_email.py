#!/usr/bin/env python3
"""
Email Assembly with Personalization

Assembles email HTML from components and inserts personalized content blocks
with A/B split logic using Braze Liquid syntax.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any

sys.path.insert(0, str(Path(__file__).parent))
from personalization_config import load_config, PersonalizationConfig


def insert_personalization_block(
    html: str,
    insertion_point: str,
    brand: str,
    campaign_type: Optional[str] = None,
    content_block_ids: Optional[Dict[str, str]] = None,
    config: Optional[PersonalizationConfig] = None
) -> str:
    """
    Insert personalized content block logic into email HTML.
    
    Args:
        html: Email HTML content
        insertion_point: Marker string where to insert personalization (e.g., "<!-- PERSONALIZATION -->")
        brand: Brand code
        campaign_type: Optional campaign type
        content_block_ids: Optional dict mapping component types to content block IDs
        config: Optional PersonalizationConfig instance
    
    Returns:
        HTML with personalization logic inserted
    """
    if config is None:
        config = load_config()
    
    # Generate personalization Liquid code
    liquid_code = config.get_personalization_liquid_code(
        brand=brand,
        campaign_type=campaign_type,
        content_block_ids=content_block_ids
    )
    
    # Wrap in comment for clarity
    wrapped_code = f"<!-- Personalized Component Block -->\n{liquid_code}\n<!-- End Personalized Component Block -->"
    
    # Insert at insertion point
    if insertion_point in html:
        html = html.replace(insertion_point, wrapped_code)
    else:
        # If insertion point not found, append before closing body tag
        if "</body>" in html:
            html = html.replace("</body>", f"{wrapped_code}\n</body>")
        else:
            # Append at end if no body tag
            html = html + "\n" + wrapped_code
    
    return html


def assemble_email_with_personalization(
    base_html: str,
    brand: str,
    campaign_type: Optional[str] = None,
    selected_rules: Optional[List[str]] = None,
    content_block_ids: Optional[Dict[str, str]] = None,
    insertion_point: str = "<!-- PERSONALIZATION -->",
    config: Optional[PersonalizationConfig] = None
) -> str:
    """
    Assemble complete email with personalization.
    
    Args:
        base_html: Base email HTML (hero, header, footer, etc.)
        brand: Brand code
        campaign_type: Optional campaign type
        selected_rules: Optional list of rule IDs to include (if None, uses all recommended)
        content_block_ids: Optional dict mapping component types to content block IDs
        insertion_point: Marker string where to insert personalization
        config: Optional PersonalizationConfig instance
    
    Returns:
        Complete email HTML with personalization
    """
    if config is None:
        config = load_config()
    
    # If specific rules selected, build custom logic
    if selected_rules:
        # Build custom personalization logic for selected rules
        lines = []
        
        for i, rule_id in enumerate(selected_rules):
            rule = config.get_rule(rule_id)
            if not rule:
                continue
            
            # Get component options
            options = config.get_component_options_for_rule(rule_id, brand)
            if not options:
                continue
            
            # Build conditional
            if i == 0:
                if rule_id == 'carted_items_module':
                    lines.append("{% if event_properties.${has_cart_items} %}")
                elif rule_id == 'viewed_items_module':
                    lines.append("{% if event_properties.${has_viewed_items} %}")
                elif rule_id == 'popular_items_module':
                    lines.append("{% else %}")
            else:
                if rule_id == 'viewed_items_module':
                    lines.append("{% elsif event_properties.${has_viewed_items} %}")
                elif rule_id == 'popular_items_module':
                    lines.append("{% else %}")
            
            # Add A/B split code
            split_code = config.get_ab_split_liquid_code(rule_id, brand, content_block_ids)
            if split_code:
                # Indent the split code
                indented = "\n".join("  " + line if line.strip() else line for line in split_code.split("\n"))
                lines.append(indented)
        
        # Close if statement
        if lines:
            lines.append("{% endif %}")
        
        liquid_code = "\n".join(lines)
    else:
        # Use standard personalization logic
        liquid_code = config.get_personalization_liquid_code(
            brand=brand,
            campaign_type=campaign_type,
            content_block_ids=content_block_ids
        )
    
    # Wrap in comment
    wrapped_code = f"<!-- Personalized Component Block -->\n{liquid_code}\n<!-- End Personalized Component Block -->"
    
    # Insert into HTML
    if insertion_point in base_html:
        html = base_html.replace(insertion_point, wrapped_code)
    else:
        # Try to find a good insertion point (after hero, before footer)
        if "<!-- END HERO -->" in base_html:
            html = base_html.replace("<!-- END HERO -->", "<!-- END HERO -->\n" + wrapped_code)
        elif "</body>" in base_html:
            html = base_html.replace("</body>", f"{wrapped_code}\n</body>")
        else:
            html = base_html + "\n" + wrapped_code
    
    return html


def generate_personalization_snippet(
    brand: str,
    campaign_type: Optional[str] = None,
    rule_id: Optional[str] = None,
    content_block_ids: Optional[Dict[str, str]] = None,
    config: Optional[PersonalizationConfig] = None
) -> str:
    """
    Generate just the personalization Liquid code snippet.
    
    Useful for previewing or testing personalization logic.
    
    Args:
        brand: Brand code
        campaign_type: Optional campaign type
        rule_id: Optional specific rule ID (if None, generates full logic)
        content_block_ids: Optional dict mapping component types to content block IDs
        config: Optional PersonalizationConfig instance
    
    Returns:
        Liquid code string
    """
    if config is None:
        config = load_config()
    
    if rule_id:
        # Generate code for specific rule
        return config.get_ab_split_liquid_code(rule_id, brand, content_block_ids)
    else:
        # Generate full personalization logic
        return config.get_personalization_liquid_code(
            brand=brand,
            campaign_type=campaign_type,
            content_block_ids=content_block_ids
        )


def main():
    parser = argparse.ArgumentParser(
        description="Assemble emails with personalized content blocks"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input HTML file"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output HTML file (default: print to stdout)"
    )
    parser.add_argument(
        "--brand",
        required=True,
        choices=["HAV", "CZ", "ID", "BUR", "STF", "TI"],
        help="Brand code"
    )
    parser.add_argument(
        "--campaign-type",
        choices=["sale_promo", "product_launch", "editorial", "reminder", "other"],
        help="Campaign type"
    )
    parser.add_argument(
        "--rules",
        nargs="+",
        help="Specific rule IDs to include (default: all recommended)"
    )
    parser.add_argument(
        "--insertion-point",
        default="<!-- PERSONALIZATION -->",
        help="Marker string where to insert personalization"
    )
    parser.add_argument(
        "--content-block-ids",
        help="JSON dict mapping component types to content block IDs"
    )
    parser.add_argument(
        "--snippet-only",
        action="store_true",
        help="Only generate Liquid snippet, don't assemble full email"
    )
    parser.add_argument(
        "--rule-id",
        help="Generate snippet for specific rule ID (use with --snippet-only)"
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        help="Path to personalization-rules.yaml"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.rules_file)
    
    # Parse content block IDs if provided
    content_block_ids = None
    if args.content_block_ids:
        import json
        content_block_ids = json.loads(args.content_block_ids)
    
    if args.snippet_only:
        # Generate snippet only
        snippet = generate_personalization_snippet(
            brand=args.brand,
            campaign_type=args.campaign_type,
            rule_id=args.rule_id,
            content_block_ids=content_block_ids,
            config=config
        )
        output = snippet
    else:
        # Assemble full email
        base_html = args.input.read_text()
        
        html = assemble_email_with_personalization(
            base_html=base_html,
            brand=args.brand,
            campaign_type=args.campaign_type,
            selected_rules=args.rules,
            content_block_ids=content_block_ids,
            insertion_point=args.insertion_point,
            config=config
        )
        output = html
    
    # Write output
    if args.output:
        args.output.write_text(output)
        print(f"Output written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
