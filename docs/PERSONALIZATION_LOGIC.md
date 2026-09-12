# Personalization Module Logic Guide

## Overview

This document explains the business logic for when to show personalized modules (carted items, viewed items, recommendations) across multiple emails in a campaign.

## Current Logic (Per-Email Decision)

The current implementation makes a decision **per email** based on user state at send time:

```
IF user has carted items (last 7 days):
  → 60% see carted items directly
  → 40% see recommendations based on cart

ELSE IF user has viewed items (last 7 days, no cart):
  → 60% see viewed items directly  
  → 40% see recommendations based on views

ELSE:
  → 100% see popular items
```

**Problem**: This doesn't account for showing the same content repeatedly across multiple emails in a week.

## Proposed Logic: Multi-Email Rotation Strategy

### Core Principle

**Don't show the same personalized content in every email.** Rotate and vary to:
- Avoid fatigue (user sees same items 7 times)
- Test different approaches (carted vs recommendations)
- Maintain relevance (items may have changed)
- Drive different actions (complete cart vs discover new)

### Decision Framework

#### 1. First Email in Campaign (Day 1)

**If user has carted items:**
- **70%** → Show carted items (strongest signal, highest intent)
- **30%** → Show recommendations based on cart (test discovery)

**Rationale**: First email should prioritize highest-intent signal (cart). But test recommendations to see if discovery drives conversions.

#### 2. Subsequent Emails (Days 2-7)

**Rotation Strategy**: Vary based on:
- **Email sequence number** (1st, 2nd, 3rd, etc.)
- **Days since carted/viewed** (freshness)
- **User engagement** (opened previous emails?)
- **Campaign type** (sale vs editorial)

### Detailed Rules by Scenario

#### Scenario A: User Has Carted Items

**Email 1 (Day 1):**
- 70% carted items
- 30% recommendations from cart

**Email 2 (Day 2-3):**
- 40% carted items (still relevant, but rotate)
- 60% recommendations from cart (expand consideration)

**Email 3 (Day 4-5):**
- 20% carted items (avoid over-saturation)
- 50% recommendations from cart
- 30% popular/trending items (fresh discovery)

**Email 4+ (Day 6-7):**
- 10% carted items (last reminder)
- 40% recommendations from cart
- 50% popular/trending items (move to discovery mode)

**Special Cases:**
- **If cart items changed** → Reset to Email 1 logic (new items = fresh signal)
- **If user opened but didn't click** → Increase recommendations (they're browsing)
- **If user clicked but didn't purchase** → Show carted items again (re-engage intent)

#### Scenario B: User Has Viewed Items (No Cart)

**Email 1 (Day 1):**
- 60% viewed items
- 40% recommendations from views

**Email 2 (Day 2-3):**
- 30% viewed items
- 70% recommendations from views

**Email 3+ (Day 4-7):**
- 10% viewed items
- 50% recommendations from views
- 40% popular/trending items

**Rationale**: Viewed items are lower intent than carted. Rotate faster to discovery mode.

#### Scenario C: No Behavioral Data

**All Emails:**
- 100% popular/trending items

**But vary the popular items:**
- Email 1: Best sellers
- Email 2: New arrivals
- Email 3: Trending now
- Email 4+: Category-specific popular items

### Implementation Approach

#### Option 1: Sequence-Based (Simpler)

Use the email's position in the campaign sequence:

```liquid
{% assign email_sequence = event_properties.${email_sequence_number} | default: 1 %}
{% assign days_since_cart = event_properties.${days_since_last_cart} | default: 0 %}

{% if event_properties.${has_cart_items} %}
  {% if email_sequence == 1 %}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 70 %}
      {{content_blocks.${carted_items_module}}}
    {% else %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% endif %}
  {% elsif email_sequence == 2 %}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 40 %}
      {{content_blocks.${carted_items_module}}}
    {% else %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% endif %}
  {% else %}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 20 %}
      {{content_blocks.${carted_items_module}}}
    {% elsif random_value < 70 %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% else %}
      {{content_blocks.${popular_items_module}}}
    {% endif %}
  {% endif %}
{% endif %}
```

#### Option 2: Days-Based (More Dynamic)

Use days since cart/viewed to determine freshness:

```liquid
{% assign days_since_cart = event_properties.${days_since_last_cart} | default: 999 %}

{% if event_properties.${has_cart_items} %}
  {% if days_since_cart <= 1 %}
    {# Fresh cart - show items directly #}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 70 %}
      {{content_blocks.${carted_items_module}}}
    {% else %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% endif %}
  {% elsif days_since_cart <= 3 %}
    {# Medium freshness - rotate #}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 40 %}
      {{content_blocks.${carted_items_module}}}
    {% else %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% endif %}
  {% else %}
    {# Stale cart - move to discovery #}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 20 %}
      {{content_blocks.${carted_items_module}}}
    {% elsif random_value < 60 %}
      {{content_blocks.${recommended_from_cart_module}}}
    {% else %}
      {{content_blocks.${popular_items_module}}}
    {% endif %}
  {% endif %}
{% endif %}
```

#### Option 3: Engagement-Based (Most Sophisticated)

Track if user opened/clicked previous emails:

```liquid
{% assign opened_previous = event_properties.${opened_campaign_email_1} | default: false %}
{% assign clicked_previous = event_properties.${clicked_campaign_email_1} | default: false %}

{% if event_properties.${has_cart_items} %}
  {% if clicked_previous %}
    {# User engaged - show carted items again #}
    {{content_blocks.${carted_items_module}}}
  {% elsif opened_previous %}
    {# User opened but didn't click - try recommendations #}
    {{content_blocks.${recommended_from_cart_module}}}
  {% else %}
    {# User didn't engage - rotate to discovery #}
    {% assign random_value = user.${random_seed} | modulo: 100 %}
    {% if random_value < 30 %}
      {{content_blocks.${carted_items_module}}}
    {% else %}
      {{content_blocks.${popular_items_module}}}
    {% endif %}
  {% endif %}
{% endif %}
```

### Recommended Approach: Hybrid

Combine sequence number + days since cart for balanced logic:

1. **Primary**: Use email sequence (1st, 2nd, 3rd email)
2. **Secondary**: Adjust based on days since cart/viewed
3. **Tertiary**: Consider engagement if available

### Campaign Type Variations

#### Sale Campaigns (High Frequency, 5-7 emails)

**Goal**: Convert carted items quickly

- **Emails 1-2**: Heavy on carted items (70-60%)
- **Emails 3-4**: Rotate to recommendations (40% cart, 60% recs)
- **Emails 5+**: Move to discovery (20% cart, 80% discovery)

#### Product Launch (3-5 emails)

**Goal**: Build awareness and consideration

- **Email 1**: New product + viewed items
- **Email 2**: Recommendations based on views
- **Email 3+**: Popular items + new product

#### Editorial Campaigns (1-2 emails)

**Goal**: Inspire and educate

- **All emails**: Popular/trending items (no personalization)
- Focus on content, not products

### Example: 7-Day Sale Campaign

**User carted 3 items on Day 1**

| Email | Day | Module | Rationale |
|-------|-----|--------|-----------|
| 1 | 1 | 70% carted, 30% recs | Fresh cart, high intent |
| 2 | 2 | 40% carted, 60% recs | Rotate to expand consideration |
| 3 | 3 | 40% carted, 60% recs | Continue rotation |
| 4 | 4 | 20% carted, 50% recs, 30% popular | Move to discovery |
| 5 | 5 | 20% carted, 50% recs, 30% popular | Discovery mode |
| 6 | 6 | 10% carted, 40% recs, 50% popular | Last reminder |
| 7 | 7 | 10% carted, 40% recs, 50% popular | Final push |

**If user opened emails 1-3 but didn't click:**
- Emails 4-7: Increase recommendations to 70% (they're browsing, not ready to buy)

**If user clicked but didn't purchase:**
- Next email: Show carted items again at 80% (re-engage intent)

### Data Requirements

To implement this logic, you need:

1. **Email sequence number**: `event_properties.${email_sequence_number}`
2. **Days since cart**: `event_properties.${days_since_last_cart}`
3. **Days since viewed**: `event_properties.${days_since_last_viewed}`
4. **Previous email engagement** (optional):
   - `event_properties.${opened_campaign_email_1}`
   - `event_properties.${clicked_campaign_email_1}`
5. **Cart freshness**: `event_properties.${cart_items_changed}` (boolean)

### Configuration Updates Needed

Update `docs/personalization-rules.yaml` to include:

```yaml
rotation_strategy:
  method: sequence_based  # or days_based, engagement_based, hybrid
  sequence_rules:
    email_1:
      carted_items: 70
      recommended_from_cart: 30
    email_2:
      carted_items: 40
      recommended_from_cart: 60
    email_3:
      carted_items: 20
      recommended_from_cart: 50
      popular_items: 30
    email_4_plus:
      carted_items: 10
      recommended_from_cart: 40
      popular_items: 50
```

## Summary

**Key Principles:**

1. **Don't repeat the same content** - Rotate across emails
2. **Start strong, fade to discovery** - Cart items early, popular items later
3. **Respect user engagement** - If they're not clicking, try different content
4. **Account for freshness** - Stale cart data = move to discovery
5. **Campaign type matters** - Sales need different logic than editorial

**Recommended Default:**
- Email 1: 70% carted, 30% recommendations
- Email 2-3: 40% carted, 60% recommendations  
- Email 4+: 20% carted, 50% recommendations, 30% popular

This balances conversion intent (carted items) with discovery (recommendations/popular) while avoiding fatigue.
