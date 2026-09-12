"""One-off script to manually trigger QA for push tasks missed during server downtime."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TASK_GIDS = [
    "1215154648107536",  # DPS: Fourth of July Event Launch (6/5)
    "1215154707882952",  # DPS: Fourth of July Sale Reminder (6/10)
    "1215187742929954",  # MP: Summer Design Trends (6/15)
    "1215187818171299",  # DPS: Fourth of July Sale Reminder (6/18)
]


async def main():
    from webhook_server import _dispatch_qa_designed_email, BRAND_GID_TO_CODE, FIELD_BRAND
    from build_sms_campaign import _get_text_value, FIELD_BRAZE_LINK, _get_enum_value_gid
    from webhook_server import fetch_task_by_gid

    for gid in TASK_GIDS:
        print(f"\n--- QA for task {gid} ---")
        raw_task = fetch_task_by_gid(gid)
        if not raw_task:
            print(f"ERROR: Could not fetch task {gid}")
            continue

        name = raw_task.get("name", gid)
        brand_gid = _get_enum_value_gid(raw_task, FIELD_BRAND)
        brand_code = BRAND_GID_TO_CODE.get(brand_gid or "")
        braze_link = _get_text_value(raw_task, FIELD_BRAZE_LINK)

        print(f"Task:       {name}")
        print(f"Brand:      {brand_code}")
        print(f"Braze link: {braze_link}")

        if not brand_code:
            print("SKIP: unknown brand")
            continue
        if not braze_link:
            print("SKIP: no Braze link")
            continue

        await _dispatch_qa_designed_email(gid, raw_task, brand_code, braze_link)
        print(f"QA dispatched for {name}")


if __name__ == "__main__":
    asyncio.run(main())
