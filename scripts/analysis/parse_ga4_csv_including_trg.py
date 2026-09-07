"""Helper function to parse GA4 CSV including TRG_ campaigns."""

import os
import csv
from pathlib import Path

def parse_ga4_csv_including_trg(csv_path, brand):
    """Parse GA4 CSV file and extract campaign metrics (including TRG_ campaigns).
    
    Returns dict mapping campaign name -> metrics dict with:
    - sessions: int
    - purchases: int (or transactions)
    - revenue: float
    """
    if not os.path.exists(csv_path):
        print(f"Warning: CSV file not found: {csv_path}")
        return {}
    
    campaigns = {}
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            # Skip comment lines at the beginning
            lines = f.readlines()
            header_line_idx = None
            for i, line in enumerate(lines):
                if line.strip() and not line.startswith('#'):
                    header_line_idx = i
                    break
            
            if header_line_idx is None:
                print(f"Warning: No header found in {csv_path}")
                return {}
            
            # Parse from header line
            f.seek(0)
            for _ in range(header_line_idx):
                next(f)
            
            reader = csv.DictReader(f)
            
            for row in reader:
                # Skip grand total rows
                row_values_str = ' '.join(str(v) for v in row.values())
                if 'Grand total' in row_values_str or not row_values_str.strip():
                    continue
                
                # Get campaign name - different CSV files use different column names
                campaign_name = None
                
                # For SF CSV, it has "Session primary channel group" and "Session campaign" columns
                # We want the "Session campaign" column value when channel is SMS
                if brand == "SF" and "Session campaign" in row:
                    channel_group = row.get("Session primary channel group (Default Channel Group)", "").strip()
                    if channel_group == "SMS" and row["Session campaign"]:
                        campaign_name = row["Session campaign"].strip()
                else:
                    # For other brands, use "Session campaign" or "campaign" column
                    for col in ['Session campaign', 'campaign']:
                        if col in row and row[col] and row[col].strip():
                            campaign_name = row[col].strip()
                            break
                
                if not campaign_name or campaign_name == '':
                    continue
                
                # NOTE: NOT filtering out TRG_ campaigns - include them all
                
                # Extract metrics based on available columns
                sessions = 0
                purchases = 0
                revenue = 0.0
                
                # Sessions
                for col in ['Sessions', 'sessions']:
                    if col in row and row[col]:
                        try:
                            sessions = int(float(row[col]))
                        except (ValueError, TypeError):
                            pass
                        break
                
                # Purchases/Transactions - different files use different column names
                # BW CSV uses "Ecommerce purchases"
                purchase_cols = ['Ecommerce purchases', 'Purchases', 'Transactions', 'purchases', 'transactions']
                for col in purchase_cols:
                    if col in row and row[col]:
                        try:
                            purchases = int(float(row[col]))
                        except (ValueError, TypeError):
                            pass
                        break
                
                # Revenue
                for col in ['Total revenue', 'totalRevenue', 'revenue']:
                    if col in row and row[col]:
                        try:
                            revenue = float(row[col])
                        except (ValueError, TypeError):
                            pass
                        break
                
                if campaign_name:
                    campaigns[campaign_name] = {
                        'sessions': sessions,
                        'purchases': purchases,
                        'revenue': revenue,
                    }
    
    except Exception as e:
        print(f"Error parsing CSV {csv_path}: {e}")
        import traceback
        traceback.print_exc()
        return {}
    
    return campaigns


