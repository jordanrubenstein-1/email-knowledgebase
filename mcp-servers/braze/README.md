# Braze MCP Server

MCP server for Braze operations with multi-brand support. Combines REST API for reads and Playwright for writes.

## Features

- **Multi-brand support**: Works with HAV, BUR, ID, STF, CZ, TI workspaces
- **API tools**: List/get campaigns, canvases, templates, analytics
- **Browser tools**: Create/archive campaigns, render HTML to screenshots
- **Persistent sessions**: Browser stays open between calls for faster operations

## Installation

```bash
cd mcp-servers/braze
uv sync
```

## Configuration

Add to your `.env`:

```bash
# REST API (per-brand)
BRAZE_API_KEY_HAV=your-hav-api-key
BRAZE_API_KEY_BUR=your-bur-api-key
# ... etc for ID, STF, CZ, TI

BRAZE_BASE_URL_HAV=https://rest.iad-07.braze.com
# ... etc

# Dashboard (Playwright)
BRAZE_DASHBOARD_URL=https://dashboard-07.braze.com
BRAZE_DASHBOARD_EMAIL=your-email@example.com
BRAZE_DASHBOARD_PASSWORD=your-password
BRAZE_TOTP_SECRET=your-base32-totp-secret
```

## MCP Config

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "braze": {
      "command": "bash",
      "args": ["-c", "set -a && source .env && set +a && exec uv run --directory mcp-servers/braze braze-mcp"]
    }
  }
}
```

## Available Tools

### API Tools (Read Operations)

| Tool | Description |
|------|-------------|
| `braze_list_campaigns` | List campaigns for a brand |
| `braze_get_campaign` | Get campaign details |
| `braze_get_campaign_analytics` | Get campaign performance metrics |
| `braze_list_canvases` | List canvases (triggered journeys) |
| `braze_get_canvas` | Get canvas structure |
| `braze_get_canvas_analytics` | Get canvas step-level analytics |
| `braze_list_templates` | List email templates |
| `braze_get_template` | Get template details |

### Browser Tools (Write Operations)

| Tool | Description |
|------|-------------|
| `braze_create_campaign` | Create draft email campaign |
| `braze_archive_campaign` | Archive a campaign |
| `braze_render_html` | Render HTML to PNG screenshot |
| `braze_close_session` | Close browser session |

## Usage Examples

```
# List HAV campaigns
Use braze_list_campaigns with brand="HAV"

# Get campaign analytics
Use braze_get_campaign_analytics with brand="HAV", campaign_id="abc123", days=30

# Create a draft campaign (dry_run=True by default)
Use braze_create_campaign with brand="HAV", name="Test", subject="Test Subject"

# Archive a campaign
Use braze_archive_campaign with brand="HAV", campaign_name="Test Campaign"

# Clean up browser session
Use braze_close_session
```

## Brand/Workspace Mapping

| Code | Braze Workspace |
|------|-----------------|
| HAV | havenly |
| BUR | Burrow - Production |
| ID | Interior Define |
| STF | St Frank |
| CZ | The Citizenry |
| TI | The Inside |

## Development

### Run tests

```bash
cd mcp-servers/braze

# All tests
uv run pytest tests/ -v

# Unit tests only (fast)
uv run pytest tests/unit -v

# Integration tests (mocked)
uv run pytest tests/integration -v

# With coverage
uv run pytest --cov=braze_mcp --cov-report=term-missing
```

### Test server locally

```bash
# Check tools load
uv run python -c "from braze_mcp.server import list_tools; import asyncio; print(asyncio.run(list_tools()))"

# Run server
uv run braze-mcp
```

## Safety

- `braze_create_campaign` defaults to `dry_run=True`
- No "Launch" or "Send" tools exposed
- All mutations require explicit brand parameter
- Browser runs headless by default
