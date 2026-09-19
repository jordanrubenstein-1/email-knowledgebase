"""Braze MCP Server - Main entry point.

Exposes Braze operations as MCP tools:
- API-based tools for reading campaigns, canvases, templates, analytics
- Playwright-based tools for creating/archiving campaigns, rendering HTML
"""

import asyncio
import json
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .config import VALID_BRANDS, BrazeConfigError
from .api.client import BrazeApiError
from .tools import api_tools
from .browser import campaign as browser_campaign

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("braze-mcp")

# Create MCP server instance
server = Server("braze-mcp")


def get_brand_description() -> str:
    """Get description of valid brand codes."""
    return f"Brand code: {', '.join(sorted(VALID_BRANDS))}"


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Braze tools."""
    return [
        # API-based tools (read operations)
        Tool(
            name="braze_list_campaigns",
            description=f"List campaigns for a brand. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code (HAV, BUR, ID, STF, CZ, TI)",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (0-indexed)",
                        "default": 0,
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived campaigns",
                        "default": False,
                    },
                },
                "required": ["brand"],
            },
        ),
        Tool(
            name="braze_get_campaign",
            description=f"Get campaign details including messages and variants. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "campaign_id": {
                        "type": "string",
                        "description": "Braze campaign ID",
                    },
                },
                "required": ["brand", "campaign_id"],
            },
        ),
        Tool(
            name="braze_get_campaign_analytics",
            description=f"Get campaign performance metrics (sends, opens, clicks). {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "campaign_id": {
                        "type": "string",
                        "description": "Braze campaign ID",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days of data (max 100)",
                        "default": 30,
                    },
                },
                "required": ["brand", "campaign_id"],
            },
        ),
        Tool(
            name="braze_list_canvases",
            description=f"List canvases (triggered journeys) for a brand. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (0-indexed)",
                        "default": 0,
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived canvases",
                        "default": False,
                    },
                },
                "required": ["brand"],
            },
        ),
        Tool(
            name="braze_get_canvas",
            description=f"Get canvas structure including steps and messages. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "canvas_id": {
                        "type": "string",
                        "description": "Braze canvas ID",
                    },
                },
                "required": ["brand", "canvas_id"],
            },
        ),
        Tool(
            name="braze_get_canvas_analytics",
            description=f"Get canvas step-level analytics. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "canvas_id": {
                        "type": "string",
                        "description": "Braze canvas ID",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days of data (max 14)",
                        "default": 14,
                    },
                },
                "required": ["brand", "canvas_id"],
            },
        ),
        Tool(
            name="braze_list_templates",
            description=f"List email templates for a brand. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max templates to return",
                        "default": 100,
                    },
                },
                "required": ["brand"],
            },
        ),
        Tool(
            name="braze_get_template",
            description=f"Get email template details including HTML. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "template_id": {
                        "type": "string",
                        "description": "Braze template ID",
                    },
                },
                "required": ["brand", "template_id"],
            },
        ),
        Tool(
            name="braze_create_template",
            description=f"Create an email template via Braze API. Templates can be used when creating campaigns to avoid slow HTML editor entry. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code (HAV, BUR, ID, STF, CZ, TI)",
                    },
                    "template_name": {
                        "type": "string",
                        "description": "Name for the email template",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body_html": {
                        "type": "string",
                        "description": "HTML body content",
                    },
                    "body_plain_text": {
                        "type": "string",
                        "description": "Plain text body (converted to HTML if body_html not provided)",
                    },
                    "preheader": {
                        "type": "string",
                        "description": "Email preheader text",
                        "default": "",
                    },
                },
                "required": ["brand", "template_name", "subject"],
            },
        ),
        # Playwright-based tools (write operations)
        Tool(
            name="braze_create_campaign",
            description=(
                f"Create a draft email campaign via Playwright. "
                f"Uses clipboard paste for fast HTML injection (~1s) instead of slow character typing. "
                f"Set use_template_api=true to use template-first approach (creates template via API, "
                f"selects it in UI). Supports scheduling, audience filters, and plain text emails. "
                f"IMPORTANT: Campaign name MUST follow the naming convention: "
                f"[TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_[DESIGN]_[HAV_AUDIENCE?]_[CONTENT_TYPE?]_Description. "
                f"Types: P (Promotional), OT (Transactional), CX, WTL, SEG. "
                f"Channels: EM (Email), SMS, PUSH. "
                f"Brands: HAV, CZ, SF, ID, TI, BW (Burrow), TRADE. "
                f"Design: D (Designed), H (HTML), PT (Plain-Text) — required for email, omit for SMS. "
                f"HAV emails must include audience: PC (Pre-Converted) or CONV (Converted). "
                f"Example: P_EM_2026_02_10_HAV_D_PC_PF_Summer_Sale_Reminder. "
                f"{get_brand_description()}"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code: HAV, CZ, SF, ID, TI, BW (Burrow), TRADE",
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Campaign name following naming convention: "
                            "[TYPE]_[CHANNEL]_[YYYY]_[MM]_[DD]_[BRAND]_[DESIGN]_Description. "
                            "E.g. P_EM_2026_02_10_CZ_D_Winter_Sale_Launch"
                        ),
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "preheader": {
                        "type": "string",
                        "description": "Email preheader text",
                        "default": "",
                    },
                    "body_html": {
                        "type": "string",
                        "description": "Email HTML body",
                    },
                    "body_plain_text": {
                        "type": "string",
                        "description": "Email plain text body (for plain text emails)",
                    },
                    "schedule_date": {
                        "type": "string",
                        "description": "Send date in YYYY-MM-DD format (e.g., '2026-02-06')",
                    },
                    "schedule_time": {
                        "type": "string",
                        "description": "Send time in HH:MM format (e.g., '07:15')",
                    },
                    "schedule_timezone": {
                        "type": "string",
                        "description": "Timezone for scheduled send (default: America/New_York)",
                        "default": "America/New_York",
                    },
                    "audience_filter_attribute": {
                        "type": "string",
                        "description": "Attribute to filter audience on (e.g., 'email')",
                    },
                    "audience_filter_operator": {
                        "type": "string",
                        "description": "Filter operator (default: 'equals')",
                        "default": "equals",
                    },
                    "audience_filter_value": {
                        "type": "string",
                        "description": "Value to filter for (e.g., specific email address)",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, don't save (preview only)",
                        "default": True,
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run browser in headless mode (default from BRAZE_HEADLESS env var, or true)",
                    },
                    "use_template_api": {
                        "type": "boolean",
                        "description": "If true, use template-first approach (create template via API, select in UI). Default false — uses fast clipboard paste instead.",
                        "default": False,
                    },
                },
                "required": ["brand", "name", "subject"],
            },
        ),
        Tool(
            name="braze_archive_campaign",
            description=f"Archive a campaign via Playwright. {get_brand_description()}",
            inputSchema={
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Brand code",
                    },
                    "campaign_name": {
                        "type": "string",
                        "description": "Campaign name to search for",
                    },
                },
                "required": ["brand", "campaign_name"],
            },
        ),
        Tool(
            name="braze_render_html",
            description="Render HTML to PNG screenshot using Playwright.",
            inputSchema={
                "type": "object",
                "properties": {
                    "html": {
                        "type": "string",
                        "description": "HTML content to render",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (default: auto-generated)",
                    },
                    "width": {
                        "type": "integer",
                        "description": "Viewport width in pixels",
                        "default": 600,
                    },
                },
                "required": ["html"],
            },
        ),
        # Session management
        Tool(
            name="braze_close_session",
            description="Close Playwright browser session to free resources.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    logger.info(f"Tool called: {name} with args: {arguments}")

    try:
        result = await dispatch_tool(name, arguments)
        return [
            TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str),
            )
        ]
    except BrazeConfigError as e:
        return [TextContent(type="text", text=f"Configuration error: {e}")]
    except BrazeApiError as e:
        return [TextContent(type="text", text=f"API error ({e.status_code}): {e}")]
    except NotImplementedError as e:
        return [TextContent(type="text", text=str(e))]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {e}")]


async def dispatch_tool(name: str, arguments: dict) -> dict | list:
    """Dispatch tool call to appropriate handler."""

    # API-based tools
    if name == "braze_list_campaigns":
        return await api_tools.list_campaigns(
            brand=arguments["brand"],
            page=arguments.get("page", 0),
            include_archived=arguments.get("include_archived", False),
        )

    elif name == "braze_get_campaign":
        return await api_tools.get_campaign(
            brand=arguments["brand"],
            campaign_id=arguments["campaign_id"],
        )

    elif name == "braze_get_campaign_analytics":
        return await api_tools.get_campaign_analytics(
            brand=arguments["brand"],
            campaign_id=arguments["campaign_id"],
            days=arguments.get("days", 30),
        )

    elif name == "braze_list_canvases":
        return await api_tools.list_canvases(
            brand=arguments["brand"],
            page=arguments.get("page", 0),
            include_archived=arguments.get("include_archived", False),
        )

    elif name == "braze_get_canvas":
        return await api_tools.get_canvas(
            brand=arguments["brand"],
            canvas_id=arguments["canvas_id"],
        )

    elif name == "braze_get_canvas_analytics":
        return await api_tools.get_canvas_analytics(
            brand=arguments["brand"],
            canvas_id=arguments["canvas_id"],
            days=arguments.get("days", 14),
        )

    elif name == "braze_list_templates":
        return await api_tools.list_templates(
            brand=arguments["brand"],
            limit=arguments.get("limit", 100),
        )

    elif name == "braze_get_template":
        return await api_tools.get_template(
            brand=arguments["brand"],
            template_id=arguments["template_id"],
        )

    elif name == "braze_create_template":
        return await api_tools.create_template(
            brand=arguments["brand"],
            template_name=arguments["template_name"],
            subject=arguments["subject"],
            body_html=arguments.get("body_html"),
            body_plain_text=arguments.get("body_plain_text"),
            preheader=arguments.get("preheader", ""),
        )

    # Playwright-based tools
    elif name == "braze_create_campaign":
        return await browser_campaign.create_campaign(
            brand=arguments["brand"],
            name=arguments["name"],
            subject=arguments["subject"],
            preheader=arguments.get("preheader", ""),
            body_html=arguments.get("body_html"),
            body_plain_text=arguments.get("body_plain_text"),
            schedule_date=arguments.get("schedule_date"),
            schedule_time=arguments.get("schedule_time"),
            schedule_timezone=arguments.get("schedule_timezone", "America/New_York"),
            audience_filter_attribute=arguments.get("audience_filter_attribute"),
            audience_filter_operator=arguments.get("audience_filter_operator", "equals"),
            audience_filter_value=arguments.get("audience_filter_value"),
            dry_run=arguments.get("dry_run", True),
            headless=arguments.get("headless"),
            use_template_api=arguments.get("use_template_api", False),
        )

    elif name == "braze_archive_campaign":
        return await browser_campaign.archive_campaign(
            brand=arguments["brand"],
            campaign_name=arguments["campaign_name"],
        )

    elif name == "braze_render_html":
        return await browser_campaign.render_html(
            html=arguments["html"],
            output_path=arguments.get("output_path"),
            width=arguments.get("width", 600),
        )

    elif name == "braze_close_session":
        return await browser_campaign.close_session()

    else:
        raise ValueError(f"Unknown tool: {name}")


def main():
    """Run the MCP server."""
    logger.info("Starting Braze MCP server...")

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main()
