"""One-off script to trigger QA for tasks that missed auto-QA while the
webhook server was down (2026-05-27).

Runs _check_and_build for each GID sequentially.  Tasks that are
'Ready for QA' with a Braze link will go straight to QA.  Tasks that
are 'Ready for QA' without a link will have _find_braze_campaign_for_task
attempt to auto-resolve it first.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from webhook_server import _check_and_build

TASK_GIDS = [
    # Ready for QA — no Braze link; _find_braze_campaign_for_task will resolve
    # (tasks with Braze links already QA'd successfully in earlier run)
    "1214163695057490",  # BW   Outdoor — Summer Ready (email, 5/31)
    "1214163795470002",  # BW   Grad Picks — Apartment Living (email, 5/30)
    "1214173707417454",  # STF  Wallpaper Edit (email, 5/29)
    "1214163987500932",  # BW   Clearance — Final Days (email, 5/29)
]


async def main():
    for gid in TASK_GIDS:
        print(f"\n{'='*60}")
        print(f"Processing task {gid}...")
        print('='*60)
        try:
            await _check_and_build(gid)
        except Exception as e:
            import traceback
            print(f"ERROR for {gid}: {e}")
            traceback.print_exc()
        # Brief pause between tasks to avoid Playwright session overlap
        await asyncio.sleep(2)

    print("\nAll tasks processed.")


if __name__ == "__main__":
    asyncio.run(main())
