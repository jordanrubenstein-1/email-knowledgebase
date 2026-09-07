#!/usr/bin/env python3
"""
Test GA4 API access to verify credentials and permissions are set up correctly.

Usage:
    uv run python scripts/test_ga4_access.py --brand HAV
    uv run python scripts/test_ga4_access.py --all
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from google.analytics.data import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    Dimension,
    Metric,
    DateRange,
)

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Brand aliases
BRAND_ALIASES = {
    "id": "ID",
    "interior define": "ID",
    "ti": "TI",
    "the inside": "TI",
    "cz": "CZ",
    "the citizenry": "CZ",
    "citizenry": "CZ",
    "hav": "HAV",
    "havenly": "HAV",
    "bur": "BUR",
    "burrow": "BUR",
    "stf": "STF",
    "st. frank": "STF",
    "st frank": "STF",
}

def normalize_brand(brand):
    """Normalize brand name to standard code."""
    if not brand:
        return None
    return BRAND_ALIASES.get(brand.lower(), brand.upper())


def get_ga4_property_id(brand):
    """Get GA4 property ID for a brand from environment."""
    brand = normalize_brand(brand)
    if not brand:
        return None
    
    property_id = os.environ.get(f"GA4_PROPERTY_ID_{brand}")
    if not property_id:
        print(f"❌ GA4_PROPERTY_ID_{brand} not set in .env")
        return None
    return property_id


def get_ga4_client():
    """Initialize GA4 Data API client using service account."""
    service_account_path = os.environ.get("GA4_SERVICE_ACCOUNT_PATH")
    if not service_account_path:
        print("❌ GA4_SERVICE_ACCOUNT_PATH not set in .env")
        return None
    
    if not os.path.exists(service_account_path):
        print(f"❌ Service account file not found: {service_account_path}")
        return None
    
    # Set environment variable for Google auth
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = service_account_path
    
    try:
        client = BetaAnalyticsDataClient()
        return client
    except Exception as e:
        print(f"❌ Error initializing GA4 client: {e}")
        return None


def test_ga4_access(client, property_id, brand):
    """Test GA4 API access by running a simple query."""
    print(f"\n{'='*60}")
    print(f"Testing GA4 access for {brand}")
    print(f"{'='*60}")
    
    # Test 1: Check property ID format
    print(f"\n1. Property ID: {property_id}")
    if not property_id.isdigit():
        print("   ⚠️  Warning: Property ID should be numeric")
    else:
        print("   ✅ Property ID format looks correct")
    
    # Test 2: Try to query GA4
    print("\n2. Testing API connection...")
    
    # Query last 7 days of data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    date_range = DateRange(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
    )
    
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[date_range],
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions")],
    )
    
    try:
        response = client.run_report(request)
        print("   ✅ API connection successful!")
        
        # Test 3: Check if we got data
        print("\n3. Checking data access...")
        if response.row_count > 0:
            print(f"   ✅ Successfully retrieved {response.row_count} rows of data")
            print("   ✅ You have read access to GA4 data")
            
            # Show sample metrics
            total_sessions = 0
            for row in response.rows:
                for metric_value in row.metric_values:
                    if metric_value.name == "sessions":
                        total_sessions += int(metric_value.value or 0)
            
            print(f"\n   Sample data (last 7 days):")
            print(f"   - Total sessions: {total_sessions:,}")
            
        else:
            print("   ⚠️  No data returned (might be normal if no traffic)")
            print("   ✅ But API access is working!")
        
        # Test 4: Try email-specific query
        print("\n4. Testing email traffic access...")
        from google.analytics.data_v1beta.types import Filter, FilterExpression, StringFilter
        
        email_filter = FilterExpression(
            filter=Filter(
                field_name="sessionSourceMedium",
                string_filter=StringFilter(
                    match_type=StringFilter.MatchType.CONTAINS,
                    value="email",
                    case_sensitive=False,
                )
            )
        )
        
        email_request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[date_range],
            dimensions=[Dimension(name="sessionSourceMedium")],
            metrics=[Metric(name="sessions")],
            dimension_filter=email_filter,
        )
        
        try:
            email_response = client.run_report(email_request)
            if email_response.row_count > 0:
                print(f"   ✅ Found {email_response.row_count} email traffic sources")
            else:
                print("   ⚠️  No email traffic found (might be normal)")
            print("   ✅ Can query email-specific data")
        except Exception as e:
            print(f"   ⚠️  Email query test failed: {e}")
            print("   (This might be okay - depends on your data)")
        
        print(f"\n{'='*60}")
        print("✅ ALL TESTS PASSED - You have proper GA4 API access!")
        print(f"{'='*60}\n")
        return True
        
    except Exception as e:
        error_str = str(e)
        print(f"   ❌ API query failed: {e}")
        
        # Provide helpful error messages
        if "PERMISSION_DENIED" in error_str or "403" in error_str:
            print("\n   🔍 Diagnosis: Permission denied")
            print("   💡 Solution: Service account needs 'Viewer' role in GA4")
            print("   📝 Action: Go to GA4 Admin → Property Access Management")
            print("            → Add service account email with 'Viewer' role")
        elif "NOT_FOUND" in error_str or "404" in error_str:
            print("\n   🔍 Diagnosis: Property not found")
            print("   💡 Solution: Check that Property ID is correct")
            print(f"   📝 Current Property ID: {property_id}")
        elif "UNAUTHENTICATED" in error_str or "401" in error_str:
            print("\n   🔍 Diagnosis: Authentication failed")
            print("   💡 Solution: Check service account JSON key file")
            print("   📝 Verify: GA4_SERVICE_ACCOUNT_PATH points to valid JSON file")
        else:
            print(f"\n   🔍 Unexpected error: {error_str}")
            print("   💡 Check Google Cloud Console for service account status")
        
        print(f"\n{'='*60}")
        print("❌ ACCESS TEST FAILED")
        print(f"{'='*60}\n")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test GA4 API access and permissions"
    )
    parser.add_argument("--brand", type=str, help="Brand to test (HAV, CZ, etc.)")
    parser.add_argument("--all", action="store_true", help="Test all brands")
    args = parser.parse_args()
    
    if not args.brand and not args.all:
        print("Error: Specify --brand or --all")
        return
    
    # Initialize GA4 client
    print("Initializing GA4 client...")
    client = get_ga4_client()
    if not client:
        print("\n❌ Failed to initialize GA4 client")
        print("Check your .env configuration:")
        print("  - GA4_SERVICE_ACCOUNT_PATH should point to JSON key file")
        sys.exit(1)
    
    print("✅ GA4 client initialized\n")
    
    # Determine brands to test
    if args.all:
        brands = ["HAV", "CZ", "STF", "BUR", "ID", "TI"]
    else:
        brands = [normalize_brand(args.brand)]
    
    results = {}
    for brand in brands:
        property_id = get_ga4_property_id(brand)
        if not property_id:
            print(f"⚠️  Skipping {brand} - no property ID configured")
            results[brand] = False
            continue
        
        success = test_ga4_access(client, property_id, brand)
        results[brand] = success
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for brand, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {brand}: {status}")
    
    all_passed = all(results.values())
    if all_passed:
        print("\n🎉 All brands have proper GA4 access!")
        print("You're ready to run: uv run python scripts/import_ga4_metrics.py")
    else:
        print("\n⚠️  Some brands failed access tests")
        print("Fix the issues above before running the import script")
        sys.exit(1)


if __name__ == "__main__":
    main()

