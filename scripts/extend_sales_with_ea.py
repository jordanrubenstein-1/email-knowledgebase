#!/usr/bin/env python3
"""
Extend sale periods to include Early Access dates.

For sales that have separate EA periods, extends the main sale period
to start from the EA start date so EA campaigns are marked as during sale.
"""

import yaml
from pathlib import Path
from collections import defaultdict

SCHEDULE_FILE = Path(__file__).parent.parent / "data" / "sale_schedules.yaml"


def main():
    print("Loading sale schedules...")
    with open(SCHEDULE_FILE) as f:
        data = yaml.safe_load(f)
    
    sales = data['sales']
    print(f"Loaded {len(sales)} sale periods\n")
    
    # Group sales by brand and find EA/main event pairs
    by_brand = defaultdict(list)
    for sale in sales:
        brand = sale.get('brand')
        if brand:
            by_brand[brand].append(sale)
    
    # Find sales with EA in name and their corresponding main sales
    updated_count = 0
    
    for brand, brand_sales in by_brand.items():
        # Sort by start date
        brand_sales.sort(key=lambda x: x.get('start_date', ''))
        
        # Look for EA sales and extend corresponding main sales
        for sale in brand_sales:
            name = sale.get('name', '').lower()
            
            # Check if this is an EA sale
            if 'ea' in name or 'early access' in name:
                # Find the corresponding main sale (usually has same name without EA)
                main_name = name.replace(' (ea)', '').replace(' (early access)', '').replace(' ea', '').replace(' early access', '')
                
                # Look for main sale with similar name and overlapping/adjacent dates
                ea_start = sale.get('start_date', '')
                ea_end = sale.get('end_date', '')
                
                for main_sale in brand_sales:
                    main_name_lower = main_sale.get('name', '').lower()
                    main_start = main_sale.get('start_date', '')
                    main_end = main_sale.get('end_date', '')
                    
                    # Check if this is the main sale (same base name, starts after EA ends or overlaps)
                    if (main_name in main_name_lower or main_name_lower in main_name) and main_sale.get('id') != sale.get('id'):
                        # If EA ends before or on main start, extend main sale to include EA
                        if ea_end <= main_start or (ea_start < main_start and ea_end >= main_start):
                            # Extend main sale to start from EA start
                            if main_start > ea_start:
                                print(f"{brand}: Extending {main_sale.get('name')} to include EA")
                                print(f"  Was: {main_start} to {main_end}")
                                main_sale['start_date'] = ea_start
                                print(f"  Now: {ea_start} to {main_end}")
                                updated_count += 1
                                print()
                            break
    
    # Also check for specific patterns like Black Friday EA
    print("Checking for specific EA patterns...")
    print()
    
    for brand, brand_sales in by_brand.items():
        # Look for Black Friday EA and Main Event
        bf_ea = [s for s in brand_sales if 'black friday' in s.get('name', '').lower() and ('ea' in s.get('name', '').lower() or 'early access' in s.get('name', '').lower())]
        bf_main = [s for s in brand_sales if 'black friday' in s.get('name', '').lower() and 'ea' not in s.get('name', '').lower() and 'early access' not in s.get('name', '').lower() and s.get('start_date', '') >= '2025-11-01']
        
        if bf_ea and bf_main:
            # Extend main to include EA
            ea_sale = bf_ea[0]
            main_sale = bf_main[0]
            
            ea_start = ea_sale.get('start_date', '')
            main_start = main_sale.get('start_date', '')
            
            if ea_start < main_start:
                print(f"{brand}: Extending Black Friday Main Event to include EA")
                print(f"  EA: {ea_sale.get('name')} ({ea_start} to {ea_sale.get('end_date')})")
                print(f"  Main was: {main_start} to {main_sale.get('end_date')}")
                main_sale['start_date'] = ea_start
                print(f"  Main now: {ea_start} to {main_sale.get('end_date')}")
                updated_count += 1
                print()
        
        # Check for EOY EA
        eoy_ea = [s for s in brand_sales if 'eoy' in s.get('name', '').lower() and ('ea' in s.get('name', '').lower() or 'early access' in s.get('name', '').lower())]
        eoy_main = [s for s in brand_sales if 'eoy' in s.get('name', '').lower() or 'end of year' in s.get('name', '').lower()]
        
        if eoy_ea:
            ea_sale = eoy_ea[0]
            # Find main EOY sale (usually the one without EA in name)
            for main_sale in eoy_main:
                if 'ea' not in main_sale.get('name', '').lower() and 'early access' not in main_sale.get('name', '').lower():
                    ea_start = ea_sale.get('start_date', '')
                    main_start = main_sale.get('start_date', '')
                    
                    if ea_start < main_start:
                        print(f"{brand}: Extending EOY sale to include EA")
                        print(f"  EA: {ea_sale.get('name')} ({ea_start} to {ea_sale.get('end_date')})")
                        print(f"  Main was: {main_start} to {main_sale.get('end_date')}")
                        main_sale['start_date'] = ea_start
                        print(f"  Main now: {ea_start} to {main_sale.get('end_date')}")
                        updated_count += 1
                        print()
                        break
    
    if updated_count > 0:
        # Save updated schedules
        with open(SCHEDULE_FILE, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        print(f"Updated {updated_count} sale periods to include EA dates")
        print(f"Saved to {SCHEDULE_FILE}")
    else:
        print("No updates needed - EA periods already included or no EA sales found")


if __name__ == "__main__":
    main()
