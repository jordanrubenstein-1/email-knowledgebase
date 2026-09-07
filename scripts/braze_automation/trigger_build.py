"""One-off script to manually trigger push auto-build for tasks missed during server downtime."""
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
    from webhook_server import _dispatch_push_build, fetch_task_by_gid
    for gid in TASK_GIDS:
        print(f"\n--- Fetching task {gid} ---")
        raw_task = fetch_task_by_gid(gid)
        if not raw_task:
            print(f"ERROR: Could not fetch task {gid}")
            continue
        print(f"Task: {raw_task.get('name')}")
        await _dispatch_push_build(gid, raw_task)
        print(f"Done: {gid}")

if __name__ == "__main__":
    asyncio.run(main())
