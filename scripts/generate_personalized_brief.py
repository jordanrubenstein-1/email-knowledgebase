#!/usr/bin/env python3
"""
Generate Personalized Email Briefs

Generates AI-assisted email briefs that include recommendations for
personalized components based on campaign type, brand, and audience.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from personalization_config import load_config, PersonalizationConfig


def generate_brief(
    campaign_name: str,
    brand: str,
    campaign_type: str,
    category: Optional[str] = None,
    audience_description: Optional[str] = None,
    config: Optional[PersonalizationConfig] = None
) -> Dict[str, Any]:
    """
    Generate a personalized email brief.
    
    Args:
        campaign_name: Name of the campaign
        brand: Brand code (HAV, CZ, ID, BUR, STF)
        campaign_type: Campaign type (sale_promo, product_launch, editorial, etc.)
        category: Optional category for additional context
        audience_description: Optional description of target audience
        config: Optional PersonalizationConfig instance
    
    Returns:
        Brief dictionary with component recommendations
    """
    if config is None:
        config = load_config()
    
    # Get recommended rules for this campaign type
    recommended_rules = config.get_rules_for_campaign_type(campaign_type)
    
    # Build component recommendations
    component_recommendations = []
    
    for rule in recommended_rules:
        # Get component options with brand overrides
        options = config.get_component_options_for_rule(rule.id, brand)
        
        if not options:
            continue
        
        # Get brand override for time windows, etc.
        brand_override = config.get_brand_override(brand, rule.id)
        
        recommendation = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "description": rule.description,
            "priority": rule.priority,
            "recommended": True,
            "component_options": []
        }
        
        # Add component options with percentages
        for option in options:
            option_info = {
                "type": option.type,
                "content_block_id": option.content_block_id,
                "percentage": option.default_percentage,
                "description": option.description or ""
            }
            recommendation["component_options"].append(option_info)
        
        # Add trigger conditions info
        if rule.trigger_conditions:
            recommendation["trigger_conditions"] = []
            for condition in rule.trigger_conditions:
                cond_info = {
                    "event": condition.event,
                    "time_window_days": condition.time_window_days,
                    "min_items": condition.min_items,
                    "fallback": condition.fallback
                }
                recommendation["trigger_conditions"].append(cond_info)
        
        # Add brand-specific overrides if present
        if brand_override:
            recommendation["brand_overrides"] = brand_override
        
        component_recommendations.append(recommendation)
    
    # Get campaign type preferences rationale
    campaign_prefs = config.campaign_type_preferences.get(campaign_type, {})
    rationale = campaign_prefs.get("rationale", "")
    
    # Build brief
    brief = {
        "campaign_name": campaign_name,
        "brand": brand,
        "campaign_type": campaign_type,
        "category": category,
        "audience_description": audience_description,
        "generated_at": datetime.now().isoformat(),
        "personalization_recommendations": {
            "rationale": rationale,
            "recommended_components": component_recommendations,
            "ab_split_method": config.ab_split_config.get("method", "random_seed"),
            "ab_split_seed": config.ab_split_config.get("seed_attribute", "user.${random_seed}")
        },
        "next_steps": [
            "Designer selects which personalized components to include",
            "Designer customizes hero image and styling",
            "AI assembles email with selected components",
            "Review and approve final email",
            "Publish to Braze"
        ]
    }
    
    return brief


def format_brief_markdown(brief: Dict[str, Any]) -> str:
    """
    Format brief as markdown for human-readable output.
    
    Args:
        brief: Brief dictionary
    
    Returns:
        Markdown formatted string
    """
    lines = []
    lines.append(f"# Email Brief: {brief['campaign_name']}")
    lines.append("")
    lines.append(f"**Brand:** {brief['brand']}  ")
    lines.append(f"**Campaign Type:** {brief['campaign_type']}  ")
    if brief.get('category'):
        lines.append(f"**Category:** {brief['category']}  ")
    lines.append(f"**Generated:** {brief['generated_at']}")
    lines.append("")
    
    if brief.get('audience_description'):
        lines.append(f"**Target Audience:** {brief['audience_description']}")
        lines.append("")
    
    # Personalization recommendations
    recs = brief['personalization_recommendations']
    lines.append("## Personalization Recommendations")
    lines.append("")
    
    if recs.get('rationale'):
        lines.append(f"*{recs['rationale']}*")
        lines.append("")
    
    for component in recs['recommended_components']:
        lines.append(f"### {component['rule_name']}")
        lines.append("")
        lines.append(f"**Priority:** {component['priority']}  ")
        lines.append(f"**Description:** {component['description']}")
        lines.append("")
        
        # Component options
        lines.append("**Component Options:**")
        for option in component['component_options']:
            lines.append(f"- **{option['type']}** ({option['percentage']}%): {option['description']}")
        lines.append("")
        
        # Trigger conditions
        if component.get('trigger_conditions'):
            lines.append("**Trigger Conditions:**")
            for condition in component['trigger_conditions']:
                cond_parts = []
                if condition.get('event'):
                    cond_parts.append(f"Event: {condition['event']}")
                if condition.get('time_window_days'):
                    cond_parts.append(f"Time window: {condition['time_window_days']} days")
                if condition.get('min_items'):
                    cond_parts.append(f"Min items: {condition['min_items']}")
                if condition.get('fallback'):
                    cond_parts.append("Fallback: true")
                if cond_parts:
                    lines.append(f"  - {', '.join(cond_parts)}")
            lines.append("")
        
        # Brand overrides
        if component.get('brand_overrides'):
            lines.append("**Brand-Specific Overrides:**")
            for key, value in component['brand_overrides'].items():
                if key != 'component_options':  # Already shown above
                    lines.append(f"  - {key}: {value}")
            lines.append("")
    
    # A/B Split info
    lines.append("### A/B Split Configuration")
    lines.append("")
    lines.append(f"- **Method:** {recs['ab_split_method']}")
    lines.append(f"- **Seed Attribute:** `{recs['ab_split_seed']}`")
    lines.append("")
    
    # Next steps
    lines.append("## Next Steps")
    lines.append("")
    for i, step in enumerate(brief['next_steps'], 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate personalized email briefs with component recommendations"
    )
    parser.add_argument(
        "--campaign-name",
        required=True,
        help="Campaign name"
    )
    parser.add_argument(
        "--brand",
        required=True,
        choices=["HAV", "CZ", "ID", "BUR", "STF", "TI"],
        help="Brand code"
    )
    parser.add_argument(
        "--campaign-type",
        required=True,
        choices=["sale_promo", "product_launch", "editorial", "reminder", "other"],
        help="Campaign type"
    )
    parser.add_argument(
        "--category",
        help="Optional category for additional context"
    )
    parser.add_argument(
        "--audience",
        help="Optional description of target audience"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "yaml"],
        default="markdown",
        help="Output format (default: markdown)"
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        help="Path to personalization-rules.yaml (default: docs/personalization-rules.yaml)"
    )
    
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.rules_file)
    
    # Validate rules
    is_valid, errors = config.validate_rules()
    if not is_valid:
        print("Error: Personalization rules have validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    
    # Generate brief
    brief = generate_brief(
        campaign_name=args.campaign_name,
        brand=args.brand,
        campaign_type=args.campaign_type,
        category=args.category,
        audience_description=args.audience,
        config=config
    )
    
    # Format output
    if args.format == "markdown":
        output = format_brief_markdown(brief)
    elif args.format == "json":
        import json
        output = json.dumps(brief, indent=2)
    elif args.format == "yaml":
        import yaml
        output = yaml.dump(brief, default_flow_style=False)
    
    # Write output
    if args.output:
        args.output.write_text(output)
        print(f"Brief written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
