# Year-Round Personalization Logic Implementation Plan

## Overview

Implement comprehensive personalization logic that works 365 days a year for all email types, incorporating Catherine's recommended modules and using recommendations extensively to avoid fatigue from popular items.

## Catherine's Recommended Modules

1. **Items carted** - Already implemented
2. **Items browsed (or categories)** - Expand viewed items to include category-level personalization
3. **Store area information** - Location-based personalization for users near physical stores
4. **Personalized offers** - Lifecycle-based (winback/reactivation, new movers)
5. **X to Y (complementary products)** - "You bought X, here's what goes with it" based on purchase history

## Core Principles

### 1. Year-Round Logic (Not Just Campaigns)

Personalization should work for:
- **Campaign emails** (sale announcements, product launches)
- **Regular batch sends** (weekly newsletters, editorial content)
- **Triggered emails** (cart abandon, browse abandon, welcome series)
- **Lifecycle emails** (winback, reactivation, new mover)

### 2. Recommendation-First Approach

**Problem**: Showing popular items repeatedly causes fatigue.

**Solution**: Use recommendations extensively based on:
- Carted items → Recommendations from cart
- Viewed items → Recommendations from views
- Purchase history → Complementary products (X to Y)
- Category preferences → Category-specific recommendations
- Style preferences → Style-based recommendations

**Logic**: If we can't show behavioral data (carted/viewed), show **personalized recommendations** instead of generic popular items.

### 3. Time Windows for Behavioral Data

- **Carted items**: Show for 14-30 days (furniture has longer consideration)
- **Viewed items**: Show for 7-14 days (faster decay)
- **After time window expires**: Switch to recommendations based on that data, not popular items

## Module Priority Logic

### Priority Order (Year-Round)

```
1. Carted Items (last 14-30 days)
   → 50% carted items
   → 50% recommendations from cart

2. Viewed Items / Categories (last 7-14 days, no cart)
   → 40% viewed items
   → 60% recommendations from views

3. Purchase History (complementary products)
   → 100% "X to Y" complementary products
   (if purchased in last 90-180 days)

4. Store Location (if near physical store)
   → 100% store-specific content
   (location-based, not product-based)

5. Personalized Offers (lifecycle-based)
   → Winback offers (if inactive 60+ days)
   → New mover offers (if address changed recently)
   → Reactivation offers (if lapsed customer)

6. Category Preferences (if available)
   → Recommendations in favorite categories
   (based on past purchases/views)

7. Recommendations (fallback)
   → Recommendations based on all available signals
   (cart + views + purchases + preferences combined)

8. Popular Items (last resort only)
   → Only if no other data available
   → Rotate: bestsellers, new arrivals, trending
```

## New Modules to Implement

### 1. Category-Based Recommendations Module

**File**: `components/category_recommendations.liquid`

**Logic**: If user viewed items in specific categories, show recommendations from those categories.

**Data Source**: 
- `event_properties.${viewedCategories}` - Array of categories user viewed
- `event_properties.${favoriteCategories}` - User's favorite categories (if available)

**Use Case**: User browsed "Sectionals" → Show sectionals recommendations, not generic popular items.

### 2. Store Location Module

**File**: `components/store_location_module.liquid`

**Logic**: If user is within X miles of a physical store, show store-specific content.

**Data Source**:
- `user.${city}` or `user.${zip_code}`
- Store locations database/attribute
- Distance calculation

**Content**:
- Store address and hours
- "Visit our [City] showroom"
- Store-specific events or promotions
- "See it in person" messaging

### 3. Personalized Offers Module

**File**: `components/personalized_offers_module.liquid`

**Logic**: Show lifecycle-based offers based on user state.

**Sub-modules**:
- **Winback**: "We miss you! [Offer]"
- **Reactivation**: "Welcome back! [Offer]"
- **New Mover**: "Congratulations on your move! [Offer]"
- **Lapsed Customer**: "It's been a while! [Offer]"

**Data Source**:
- `user.${last_purchase_date}` - Days since last purchase
- `user.${last_email_open_date}` - Days since last engagement
- `user.${address_changed_date}` - Recent address change
- `user.${customer_segment}` - Winback, reactivation, etc.

### 4. Complementary Products Module (X to Y)

**File**: `components/complementary_products_module.liquid`

**Logic**: "You bought X, here's what goes with it"

**Data Source**:
- `event_properties.${recentPurchases}` - Array of recent purchases
- `event_properties.${complementaryProducts}` - Products that complement purchases
- Or: `user.${last_purchase_product_id}` + recommendation engine

**Content**:
- "Complete the look" messaging
- "Frequently bought together"
- "You might also like" based on purchase

**Time Window**: Show for 90-180 days after purchase (furniture has long consideration)

### 5. Multi-Signal Recommendations Module

**File**: `components/multi_signal_recommendations.liquid`

**Logic**: Combine all available signals for best recommendations.

**Signals Combined**:
- Carted items
- Viewed items
- Purchase history
- Category preferences
- Style preferences (if available)

**Use Case**: When no single signal is strong enough, combine them for personalized recommendations instead of showing popular items.

## Updated Personalization Rules Schema

Update `docs/personalization-rules.yaml` to include:

```yaml
personalization_rules:
  - id: carted_items_module
    time_window_days: 30  # Longer for furniture
    component_options:
      - type: carted_items
        default_percentage: 50
      - type: recommended_from_cart
        default_percentage: 50  # Always show recs, not popular
  
  - id: viewed_items_module
    time_window_days: 14
    component_options:
      - type: viewed_items
        default_percentage: 40
      - type: recommended_from_views
        default_percentage: 60
  
  - id: category_recommendations_module
    priority: 3
    trigger_conditions:
      - event: category_viewed
        time_window_days: 30
    component_options:
      - type: category_recommendations
        default_percentage: 100
  
  - id: complementary_products_module
    priority: 4
    trigger_conditions:
      - event: purchase_completed
        time_window_days: 180
    component_options:
      - type: complementary_products
        default_percentage: 100
  
  - id: store_location_module
    priority: 5
    trigger_conditions:
      - location: near_store
        max_distance_miles: 25
    component_options:
      - type: store_location
        default_percentage: 100
  
  - id: personalized_offers_module
    priority: 6
    trigger_conditions:
      - lifecycle: winback  # 60+ days inactive
      - lifecycle: reactivation  # Lapsed customer
      - lifecycle: new_mover  # Address changed
    component_options:
      - type: personalized_offer
        default_percentage: 100
  
  - id: multi_signal_recommendations_module
    priority: 7
    description: Combines all signals for personalized recommendations
    component_options:
      - type: multi_signal_recommendations
        default_percentage: 100
  
  - id: popular_items_module
    priority: 8  # Last resort only
    trigger_conditions:
      - fallback: true
    component_options:
      - type: popular_items
        default_percentage: 100
      # Rotate: bestsellers, new arrivals, trending
```

## Year-Round Logic Flow

### Decision Tree

```
IF carted items (last 30 days):
  → 50% carted items
  → 50% recommendations from cart

ELSE IF viewed items (last 14 days):
  → 40% viewed items
  → 60% recommendations from views

ELSE IF purchased recently (last 180 days):
  → 100% complementary products (X to Y)

ELSE IF near physical store:
  → 100% store location content

ELSE IF lifecycle trigger (winback/reactivation/new mover):
  → 100% personalized offer

ELSE IF category preferences available:
  → 100% category recommendations

ELSE IF any behavioral data exists (old cart/views):
  → 100% multi-signal recommendations
  (combine all old signals for personalized recs)

ELSE:
  → 100% popular items (last resort)
  → Rotate: bestsellers → new arrivals → trending
```

## Implementation Steps

1. **Create new Liquid templates** for:
   - `category_recommendations.liquid`
   - `store_location_module.liquid`
   - `personalized_offers_module.liquid`
   - `complementary_products_module.liquid`
   - `multi_signal_recommendations.liquid`

2. **Update personalization-rules.yaml** with new modules and priority order

3. **Update components.yaml** to register new modules

4. **Update personalization_config.py** to handle new module types and priority logic

5. **Update PERSONALIZATION_LOGIC.md** with year-round logic documentation

6. **Update assemble_email.py** to support new module types

## Key Design Decisions

- **Recommendations over popular**: Always prefer personalized recommendations over generic popular items
- **Longer time windows**: Furniture has longer consideration (30 days for cart, 180 days for complementary)
- **Multi-signal approach**: Combine old signals for recommendations instead of showing popular
- **Lifecycle integration**: Personalization includes lifecycle triggers (winback, reactivation)
- **Location-based**: Store proximity is a personalization signal
- **Category-level**: Personalize at category level when product-level data isn't available

## Data Requirements

To implement fully, need access to:
- Purchase history (for complementary products)
- User location/zip code (for store proximity)
- Lifecycle attributes (last purchase date, inactivity period)
- Category preferences (favorite categories)
- Store locations database

If not all available, implement what's possible and document what's needed.
