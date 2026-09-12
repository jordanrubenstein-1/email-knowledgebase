"""One-off script: build the missing PC (DPS) push campaign for a combined DPS+MP task
where only the CONV variant was built.

Usage:
  uv run python scripts/braze_automation/build_push_pc_only.py --task 1215978945622365
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from build_push_campaign import (
    fetch_task_by_gid,
    parse_asana_push_task,
    build_single_push_campaign,
    load_brand_config,
    append_asana_comment,
    update_asana_with_braze_link,
    _get_text_value,
    FIELD_BRAZE_LINK,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Build missing PC push variant for a combined DPS+MP task")
    parser.add_argument("--task", required=True, help="Asana task GID")
    parser.add_argument("--no-headless", action="store_false", dest="headless")
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    task_gid = args.task
    logger.info(f"Fetching task {task_gid}...")
    raw_task = fetch_task_by_gid(task_gid)
    if not raw_task:
        logger.error(f"Task {task_gid} not found")
        return

    parsed_tasks = parse_asana_push_task(raw_task)
    if not parsed_tasks:
        logger.error("Could not parse push task")
        return

    # Filter to PC only
    pc_tasks = [t for t in parsed_tasks if t.get("variant") == "HAV_PC"]
    if not pc_tasks:
        logger.error("No HAV_PC variant found in parsed tasks")
        return

    logger.info(f"Building HAV_PC variant: {pc_tasks[0]['campaign_name']}")

    global_config = load_brand_config()
    result = await build_single_push_campaign(
        task=pc_tasks[0],
        global_config=global_config,
        dry_run=False,
        auto_confirm=True,
        headless=args.headless,
    )

    if not result.get("success"):
        logger.error(f"PC build failed: {result}")
        return

    pc_url = result["braze_url"]
    logger.info(f"PC campaign built: {pc_url}")

    # Get the existing CONV URL from the Braze Link field (written by the earlier CONV build)
    conv_url = _get_text_value(raw_task, FIELD_BRAZE_LINK) or "(CONV URL not found in Asana field)"

    # Update the Braze Link field with both links
    combined_links = f"- Pre-Converted (DPS): {pc_url}\n- Converted (MP): {conv_url}"
    if update_asana_with_braze_link(task_gid, combined_links):
        logger.info("Asana Braze Link field updated with both links")
    else:
        logger.warning("Failed to update Braze Link field")

    # Post a combined comment matching the normal _writeback_to_asana format
    comment_lines = [
        "Push campaigns have been automatically created in Braze "
        "and are ready for review and scheduling.\n",
        f"- Pre-Converted (DPS): {pc_url}",
        f"- Converted (MP): {conv_url}",
    ]
    comment = "\n".join(comment_lines)
    if append_asana_comment(task_gid, comment):
        logger.info("Asana comment posted with both links")
    else:
        logger.warning("Failed to post Asana comment")

    logger.info("Done. Task status was already set to Ready for QA — leaving it as-is.")


if __name__ == "__main__":
    asyncio.run(main())
