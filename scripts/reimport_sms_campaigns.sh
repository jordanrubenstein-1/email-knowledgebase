#!/bin/bash
# Helper script to re-import SMS campaigns for all brands
# This ensures SMS click data is captured correctly using the fixed import script

BRANDS="ID CZ STF BUR HAV TI"

echo "Re-importing SMS campaigns for all brands..."
echo "This will update analytics data with correct SMS click tracking."
echo ""

for BRAND in $BRANDS; do
    echo "Importing campaigns for $BRAND..."
    python3 scripts/import_braze.py --brand $BRAND --skip-existing
    echo ""
done

echo "Done! SMS campaigns have been re-imported with corrected click tracking."
echo "Run 'python3 scripts/analyze_engagement.py' to regenerate the analysis report."







