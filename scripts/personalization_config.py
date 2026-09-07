#!/usr/bin/env python3
"""
Personalization Rules Configuration Loader and Validator

Loads personalization rules from YAML, validates configurations,
and provides helper functions for rule evaluation.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass


@dataclass
class ComponentOption:
    """Represents a component option within a personalization rule."""
    type: str
    content_block_id: str
    default_percentage: int
    description: Optional[str] = None


@dataclass
class TriggerCondition:
    """Represents a trigger condition for a personalization rule."""
    event: Optional[str] = None
    time_window_days: Optional[int] = None
    min_items: Optional[int] = None
    data_source: Optional[str] = None
    fallback_if_no_cart: Optional[bool] = None
    fallback: Optional[bool] = None


@dataclass
class PersonalizationRule:
    """Represents a personalization rule configuration."""
    id: str
    name: str
    description: str
    priority: int
    trigger_conditions: List[TriggerCondition]
    component_options: List[ComponentOption]


class PersonalizationConfig:
    """Manages personalization rules configuration."""
    
    def __init__(self, rules_file: Optional[Path] = None):
        """
        Initialize personalization config.
        
        Args:
            rules_file: Path to personalization-rules.yaml. If None, uses default location.
        """
        if rules_file is None:
            # Default to docs/personalization-rules.yaml relative to script location
            script_dir = Path(__file__).parent.parent
            rules_file = script_dir / "docs" / "personalization-rules.yaml"
        
        self.rules_file = Path(rules_file)
        self.rules: List[PersonalizationRule] = []
        self.brand_overrides: Dict[str, Dict[str, Any]] = {}
        self.campaign_type_preferences: Dict[str, Dict[str, Any]] = {}
        self.ab_split_config: Dict[str, Any] = {}
        
        self._load_rules()
    
    def _load_rules(self):
        """Load and parse personalization rules from YAML file."""
        if not self.rules_file.exists():
            raise FileNotFoundError(f"Personalization rules file not found: {self.rules_file}")
        
        with open(self.rules_file, 'r') as f:
            data = yaml.safe_load(f)
        
        # Load rules
        for rule_data in data.get('personalization_rules', []):
            rule = PersonalizationRule(
                id=rule_data['id'],
                name=rule_data['name'],
                description=rule_data.get('description', ''),
                priority=rule_data.get('priority', 999),
                trigger_conditions=[
                    TriggerCondition(**condition) for condition in rule_data.get('trigger_conditions', [])
                ],
                component_options=[
                    ComponentOption(**option) for option in rule_data.get('component_options', [])
                ]
            )
            self.rules.append(rule)
        
        # Sort rules by priority (lower number = higher priority)
        self.rules.sort(key=lambda r: r.priority)
        
        # Load brand overrides
        self.brand_overrides = data.get('brand_overrides', {})
        
        # Load campaign type preferences
        self.campaign_type_preferences = data.get('campaign_type_preferences', {})
        
        # Load A/B split configuration
        self.ab_split_config = data.get('ab_split', {})
    
    def get_rule(self, rule_id: str) -> Optional[PersonalizationRule]:
        """Get a rule by ID."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None
    
    def get_rules_for_campaign_type(self, campaign_type: str) -> List[PersonalizationRule]:
        """
        Get recommended rules for a campaign type.
        
        Args:
            campaign_type: Campaign type (e.g., 'sale_promo', 'product_launch')
        
        Returns:
            List of recommended rules for this campaign type
        """
        preferences = self.campaign_type_preferences.get(campaign_type, {})
        preferred_modules = preferences.get('preferred_modules', [])
        
        if not preferred_modules:
            # Return all rules if no specific preferences
            return self.rules
        
        # Map module names to rule IDs
        module_to_rule = {
            'carted_items_module': 'carted_items_module',
            'viewed_items_module': 'viewed_items_module',
            'popular_items_module': 'popular_items_module',
            'recommended_from_cart': 'carted_items_module',  # Component option within rule
            'recommended_from_views': 'viewed_items_module',  # Component option within rule
        }
        
        recommended_rules = []
        for module in preferred_modules:
            rule_id = module_to_rule.get(module)
            if rule_id:
                rule = self.get_rule(rule_id)
                if rule and rule not in recommended_rules:
                    recommended_rules.append(rule)
        
        # If no matches, return all rules
        return recommended_rules if recommended_rules else self.rules
    
    def get_brand_override(self, brand: str, rule_id: str) -> Optional[Dict[str, Any]]:
        """
        Get brand-specific override for a rule.
        
        Args:
            brand: Brand code (HAV, CZ, ID, BUR, STF)
            rule_id: Rule ID
        
        Returns:
            Override configuration or None
        """
        brand_config = self.brand_overrides.get(brand, {})
        return brand_config.get(rule_id)
    
    def get_component_options_for_rule(
        self, 
        rule_id: str, 
        brand: Optional[str] = None
    ) -> List[ComponentOption]:
        """
        Get component options for a rule, applying brand overrides if provided.
        
        Args:
            rule_id: Rule ID
            brand: Optional brand code for overrides
        
        Returns:
            List of component options
        """
        rule = self.get_rule(rule_id)
        if not rule:
            return []
        
        # Check for brand override
        if brand:
            override = self.get_brand_override(brand, rule_id)
            if override and 'component_options' in override:
                # Merge override options with original options (override takes precedence)
                original_options = {opt.type: opt for opt in rule.component_options}
                merged_options = []
                
                for override_opt in override['component_options']:
                    opt_type = override_opt['type']
                    if opt_type in original_options:
                        # Merge: use override values but keep original content_block_id if not in override
                        original = original_options[opt_type]
                        merged_opt = {
                            'type': opt_type,
                            'content_block_id': override_opt.get('content_block_id', original.content_block_id),
                            'default_percentage': override_opt.get('default_percentage', original.default_percentage),
                            'description': override_opt.get('description', original.description)
                        }
                        merged_options.append(ComponentOption(**merged_opt))
                    else:
                        # New option from override
                        merged_options.append(ComponentOption(**override_opt))
                
                return merged_options
        
        # Return default options
        return rule.component_options
    
    def validate_rules(self) -> Tuple[bool, List[str]]:
        """
        Validate personalization rules configuration.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check that rules exist
        if not self.rules:
            errors.append("No personalization rules found")
            return False, errors
        
        # Validate each rule
        for rule in self.rules:
            # Check required fields
            if not rule.id:
                errors.append(f"Rule missing ID: {rule.name}")
            
            if not rule.component_options:
                errors.append(f"Rule '{rule.id}' has no component options")
            
            # Validate component options percentages sum to 100
            total_percentage = sum(opt.default_percentage for opt in rule.component_options)
            if total_percentage != 100:
                errors.append(
                    f"Rule '{rule.id}' component options percentages sum to {total_percentage}, "
                    f"expected 100"
                )
            
            # Validate percentages are between 0 and 100
            for opt in rule.component_options:
                if not (0 <= opt.default_percentage <= 100):
                    errors.append(
                        f"Rule '{rule.id}' option '{opt.type}' has invalid percentage: "
                        f"{opt.default_percentage}"
                    )
        
        # Validate A/B split config
        if self.ab_split_config:
            method = self.ab_split_config.get('method')
            if method not in ['random_seed', 'user_attribute']:
                errors.append(f"Invalid A/B split method: {method}")
        
        return len(errors) == 0, errors
    
    def get_ab_split_liquid_code(
        self,
        rule_id: str,
        brand: Optional[str] = None,
        content_block_ids: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate Braze Liquid code for A/B split logic.
        
        Args:
            rule_id: Rule ID
            brand: Optional brand code for overrides
            content_block_ids: Optional dict mapping component types to content block IDs
        
        Returns:
            Liquid code string for A/B split
        """
        options = self.get_component_options_for_rule(rule_id, brand)
        if not options:
            return ""
        
        # Get A/B split configuration
        seed_attribute = self.ab_split_config.get('seed_attribute', 'user.${random_seed}')
        modulo_base = self.ab_split_config.get('modulo_base', 100)
        
        # Build Liquid code
        lines = []
        cumulative = 0
        
        for i, option in enumerate(options):
            if i == 0:
                # First option
                lines.append(f"  {{% assign random_value = {seed_attribute} | modulo: {modulo_base} %}}")
                lines.append(f"  {{% if random_value < {option.default_percentage} %}}")
            else:
                # Subsequent options
                lines.append(f"  {{% elsif random_value < {cumulative + option.default_percentage} %}}")
            
            # Get content block ID
            if content_block_ids and option.type in content_block_ids:
                cb_id = content_block_ids[option.type]
            else:
                cb_id = option.content_block_id
            
            # Content block reference - cb_id already contains ${...} format
            # Use double braces to escape in f-string
            lines.append(f"    {{{{content_blocks.{cb_id} | id: 'cb_{option.type}'}}}}")
            
            cumulative += option.default_percentage
        
        # Close if statement
        lines.append("  {% endif %}")
        
        return "\n".join(lines)
    
    def get_personalization_liquid_code(
        self,
        brand: Optional[str] = None,
        campaign_type: Optional[str] = None,
        content_block_ids: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate complete Braze Liquid code for personalization logic.
        
        This generates the full conditional logic checking for cart items,
        viewed items, and falling back to popular items.
        
        Args:
            brand: Optional brand code
            campaign_type: Optional campaign type for rule selection
            content_block_ids: Optional dict mapping component types to content block IDs
        
        Returns:
            Complete Liquid code string
        """
        # Get rules in priority order
        if campaign_type:
            rules = self.get_rules_for_campaign_type(campaign_type)
        else:
            rules = self.rules
        
        lines = []
        
        # Build conditional chain
        for i, rule in enumerate(rules):
            if i == 0:
                # Use double braces to escape - output will be single braces for Liquid
                lines.append("{{% if event_properties.${{has_cart_items}} %}}")
            elif rule.id == 'viewed_items_module':
                lines.append("{{% elsif event_properties.${{has_viewed_items}} %}}")
            elif rule.id == 'popular_items_module':
                lines.append("{{% else %}}")
            
            # Add A/B split code for this rule
            split_code = self.get_ab_split_liquid_code(rule.id, brand, content_block_ids)
            if split_code:
                lines.append(split_code)
        
        # Close if statement
        lines.append("{{% endif %}}")
        
        return "\n".join(lines)


def load_config(rules_file: Optional[Path] = None) -> PersonalizationConfig:
    """
    Convenience function to load personalization config.
    
    Args:
        rules_file: Optional path to rules file
    
    Returns:
        PersonalizationConfig instance
    """
    return PersonalizationConfig(rules_file)


if __name__ == "__main__":
    # Test loading and validation
    config = load_config()
    is_valid, errors = config.validate_rules()
    
    if is_valid:
        print("✓ Personalization rules are valid")
        print(f"  Loaded {len(config.rules)} rules")
        for rule in config.rules:
            print(f"    - {rule.id}: {rule.name} (priority {rule.priority})")
    else:
        print("✗ Personalization rules have errors:")
        for error in errors:
            print(f"  - {error}")
