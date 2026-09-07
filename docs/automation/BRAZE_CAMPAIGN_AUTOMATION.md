# Braze Plain Text Email Campaign Automation

This guide covers how to automatically create and launch plain text email campaigns in Braze using the automation scripts in this repository.

## Overview

The automation system allows you to:
- Create plain text email campaigns programmatically
- Schedule campaigns for future sends
- Launch campaigns immediately
- Batch process multiple campaigns
- Validate campaign configurations before creation

## Prerequisites

### Braze API Access

1. **API Key**: You need a Braze API key with the following permissions/scopes:
   - `campaigns.create` - Create new campaigns
   - `campaigns.trigger.send` - Launch campaigns
   - `campaigns.trigger.schedule.create` - Schedule campaigns
   - `content_blocks.create` - Create email content blocks
   - `segments.list` - Validate audience segments (optional but recommended)

2. **API Key Configuration**: Add your API keys to `.env` file:
   ```bash
   BRAZE_API_KEY_HAV=your-hav-api-key
   BRAZE_BASE_URL_HAV=https://rest.iad-01.braze.com
   BRAZE_API_KEY_CZ=your-cz-api-key
   BRAZE_BASE_URL_CZ=https://rest.iad-02.braze.com
   # ... etc for other brands
   ```

### Python Dependencies

Install required packages:
```bash
uv sync
# or
pip install -r requirements.txt
```

Required packages:
- `requests` - HTTP requests to Braze API
- `pyyaml` - YAML file parsing
- `python-dotenv` - Environment variable management
- `pytz` - Timezone handling

## Campaign Configuration Schema

Campaigns are defined using YAML files. See `campaigns/_template-campaign-config.yaml` for a complete example.

### Required Fields

```yaml
campaign:
  name: "P_2025_01_15_PT_HAV_Sale_Reminder"  # Campaign name
  brand: "HAV"  # Brand code: HAV, CZ, ID, BUR, STF, TI
  category: "reminder"  # reminder, sale_promo, editorial, product_launch, other
  type: "announcement"  # sale, seasonal, product_launch, lifecycle, announcement
  
  send:
    date: "2025-01-15"  # YYYY-MM-DD
    time: "14:00"  # HH:MM (24-hour format)
    timezone: "America/New_York"  # IANA timezone
  
  email:
    subject: "Your discount is now up to 70% off"
    body: |
      Plain text email body here.
      Can include {{ personalization }} variables.
    
    cta_links:
      - text: "Shop Now"
        url: "https://example.com/shop"
        priority: 1
  
  audience:
    type: "segment"  # segment, connected_audience, or user_list
    id: "segment-uuid-here"  # Braze segment ID
  
  settings:
    subscription_group: "Marketing"  # Marketing or Transactional
```

### Field Descriptions

#### Campaign Metadata
- **name**: Campaign name following your naming convention (e.g., `P_YYYY_MM_DD_PT_BRAND_Description`)
- **brand**: Brand code (HAV, CZ, ID, BUR, STF, TI)
- **category**: Campaign category for analysis
- **type**: Campaign type classification

#### Send Schedule
- **date**: Send date in `YYYY-MM-DD` format
- **time**: Send time in `HH:MM` format (24-hour)
- **timezone**: IANA timezone string (e.g., `America/New_York`, `UTC`)

#### Email Content
- **subject**: Email subject line (required)
- **preheader**: Optional preheader text
- **body**: Plain text email body. Supports Liquid templating syntax for personalization
- **cta_links**: Array of call-to-action links
  - **text**: Link text/button label
  - **url**: Full URL (must start with http:// or https://)
  - **priority**: Optional ordering (lower numbers appear first)

#### Audience
- **type**: One of:
  - `segment` - Use a Braze segment (requires `id`)
  - `connected_audience` - Use a connected audience (requires `connected_audience_id`)
  - `user_list` - Send to specific users (requires `external_user_ids` array)

#### Settings
- **subscription_group**: `Marketing` or `Transactional`
- **frequency_capping**: Optional frequency limits
  - **enabled**: `true` or `false`
  - **max_sends**: Maximum sends per user
  - **period_days**: Period in days for the cap

## Usage

### Safety Feature: No Automatic Sending

**IMPORTANT**: By default, campaigns are created but NOT scheduled or sent. This prevents accidental email sends. You must explicitly use the `--schedule` flag to schedule a campaign.

### Single Campaign Creation

Create a single campaign from a YAML config file:

```bash
# Create campaign (SAFE: creates but does NOT schedule/send)
uv run python scripts/create_braze_campaign.py \
  --config campaigns/my-campaign.yaml \
  --brand HAV

# Validate without creating (dry-run)
uv run python scripts/create_braze_campaign.py \
  --config campaigns/my-campaign.yaml \
  --dry-run

# Create AND schedule campaign (requires explicit permission)
uv run python scripts/create_braze_campaign.py \
  --config campaigns/my-campaign.yaml \
  --brand HAV \
  --schedule
```

When using `--schedule`, you'll be prompted to confirm before scheduling.

### Batch Campaign Creation

Process multiple campaigns from a directory:

```bash
# Process all YAML files (SAFE: creates but does NOT schedule/send)
uv run python scripts/create_braze_campaigns_batch.py \
  --dir campaigns/to-create/ \
  --brand HAV \
  --workers 5

# Dry-run batch processing
uv run python scripts/create_braze_campaigns_batch.py \
  --dir campaigns/to-create/ \
  --dry-run

# Process AND schedule campaigns (requires explicit permission)
uv run python scripts/create_braze_campaigns_batch.py \
  --dir campaigns/to-create/ \
  --brand HAV \
  --workers 5 \
  --schedule
```

**Options:**
- `--dir`: Directory containing campaign config YAML files
- `--brand`: Brand code (overrides config if provided)
- `--workers`: Number of parallel workers (default: 3)
- `--dry-run`: Validate without creating campaigns
- `--schedule`: Schedule campaigns after creation (requires confirmation)

## Workflow

The automation follows this workflow:

1. **Load Configuration**: Read and parse YAML config file
2. **Validate**: Check all required fields, date formats, URLs, etc.
3. **Create Content Block**: Create plain text email template in Braze
4. **Create Campaign**: Create campaign in Braze (NOT scheduled by default)
5. **Schedule** (optional): Set send date/time (only if `--schedule` flag is used)
6. **Save Record**: Save campaign metadata to knowledgebase

**Safety**: By default, step 5 is skipped. Campaigns are created but not scheduled, allowing you to review them in the Braze dashboard before scheduling.

## Validation

The system validates:

- ✅ Brand code is valid
- ✅ Category and type are valid
- ✅ Send date/time is in the future
- ✅ Timezone is valid IANA timezone
- ✅ Subject line is not empty
- ✅ Email body is not empty
- ✅ At least one CTA link is provided
- ✅ CTA URLs are valid (start with http:// or https://)
- ✅ Audience configuration is valid
- ✅ Subscription group is valid

## Error Handling

### Rate Limiting

The system automatically handles Braze API rate limits (429 errors):
- Implements exponential backoff retry logic
- Respects `Retry-After` headers when provided
- Retries up to 3 times by default

### API Errors

Common API errors and solutions:

**401 Unauthorized**
- Check that your API key is correct in `.env`
- Verify the API key has required permissions

**404 Not Found**
- Verify the segment ID exists in Braze
- Check that the endpoint URL is correct

**422 Validation Error**
- Review the error message for specific field issues
- Check that all required fields are provided
- Verify data formats match requirements

**500 Server Error**
- Braze API issue - retry after a delay
- Check Braze status page

### Validation Errors

If validation fails, the script will:
- List all validation errors
- Provide specific field-level feedback
- Exit without creating the campaign

## Troubleshooting

### Campaign Not Created

1. **Check validation errors**: Run with `--dry-run` to see validation issues
2. **Verify API key**: Ensure API key is set correctly in `.env`
3. **Check Braze logs**: Review Braze dashboard for API errors
4. **Test API connection**: Verify you can make API calls to Braze

### Content Block Creation Fails

- Ensure `content_blocks.create` permission is granted
- Check that email body doesn't contain unsupported HTML
- Verify content block name is unique

### Campaign Scheduling Fails

- Verify send datetime is in the future
- Check timezone format (must be valid IANA timezone)
- Ensure campaign was created successfully first

### Audience Issues

- Verify segment ID exists in Braze
- Check that segment is active
- For user lists, ensure external_user_ids are valid

## Best Practices

1. **Always use dry-run first**: Validate configurations before creating campaigns
   ```bash
   uv run python scripts/create_braze_campaign.py --config my-campaign.yaml --dry-run
   ```

2. **Create without scheduling first**: Test campaign creation without scheduling
   ```bash
   uv run python scripts/create_braze_campaign.py --config my-campaign.yaml --brand HAV
   # Review in Braze dashboard, then schedule manually or use --schedule flag
   ```

3. **Review before scheduling**: Always review campaigns in Braze dashboard before using `--schedule`

4. **Test with single campaign**: Before batch processing, test with one campaign

5. **Monitor rate limits**: Use appropriate `--workers` count to avoid rate limits

6. **Use descriptive names**: Follow naming conventions for easy tracking

7. **Validate segments**: Ensure audience segments exist before creating campaigns

8. **Check send times**: Verify send datetime is correct timezone and in the future

## API Rate Limits

Braze API has rate limits that vary by endpoint. The automation:
- Implements automatic retry with exponential backoff
- Respects `Retry-After` headers
- Limits parallel workers in batch processing

**Recommendations:**
- Use 3-5 workers for batch processing
- Add delays between large batches
- Monitor API usage in Braze dashboard

## Examples

### Example 1: Simple Sale Reminder

```yaml
campaign:
  name: "P_2025_01_20_PT_HAV_Sale_Reminder"
  brand: "HAV"
  category: "reminder"
  type: "sale"
  
  send:
    date: "2025-01-20"
    time: "10:00"
    timezone: "America/New_York"
  
  email:
    subject: "Last chance: 50% off ends tonight"
    body: |
      Hi there,
      
      Don't miss out! Our sale ends tonight at midnight.
      
      Shop now and save 50% on everything.
    
    cta_links:
      - text: "Shop Now"
        url: "https://havenly.com/sale"
        priority: 1
  
  audience:
    type: "segment"
    id: "abc123-def456-ghi789"
  
  settings:
    subscription_group: "Marketing"
```

### Example 2: Product Launch with Personalization

```yaml
campaign:
  name: "P_2025_02_01_PT_CZ_New_Collection_Launch"
  brand: "CZ"
  category: "product_launch"
  type: "product_launch"
  
  send:
    date: "2025-02-01"
    time: "09:00"
    timezone: "America/New_York"
  
  email:
    subject: "Introducing our new {{ collection_name }} collection"
    body: |
      Hi {{ first_name }},
      
      We're excited to introduce our new {{ collection_name }} collection.
      
      Discover handcrafted pieces from around the world.
    
    cta_links:
      - text: "Explore Collection"
        url: "https://thecitizenry.com/collections/{{ collection_slug }}"
        priority: 1
      - text: "Shop All"
        url: "https://thecitizenry.com/shop"
        priority: 2
  
  audience:
    type: "segment"
    id: "xyz789-abc123-def456"
  
  settings:
    subscription_group: "Marketing"
    frequency_capping:
      enabled: true
      max_sends: 1
      period_days: 30
```

## Integration with Knowledgebase

Created campaigns are automatically saved to the knowledgebase:
- Saved to `campaigns/` directory
- Follows existing naming convention
- Includes Braze IDs for tracking
- Links back to original config file

## Support

For issues or questions:
1. Check validation errors with `--dry-run`
2. Review Braze API documentation
3. Check Braze dashboard for campaign status
4. Review error messages for specific guidance

## Related Files

- `scripts/create_braze_campaign.py` - Main campaign creation script
- `scripts/create_braze_campaigns_batch.py` - Batch processing script
- `scripts/braze_campaign_api.py` - Braze API wrapper functions
- `scripts/validate_campaign_config.py` - Validation logic
- `campaigns/_template-campaign-config.yaml` - Configuration template
