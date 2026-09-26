"""
Backward-compatibility shim for build_ti_designed_email.py.

The TI designed email builder has been refactored into a generic Klaviyo builder.
Use build_klaviyo_designed_email.py going forward:

    uv run python scripts/braze_automation/build_klaviyo_designed_email.py \\
      --task-gid GID --brand TI [--dry-run] [--skip-asana] [--half-width-from N]

All functions and the main() entry point are re-exported from the new module.
"""
from build_klaviyo_designed_email import (  # noqa: F401
    build_klaviyo_designed_email as build_ti_designed_email,
    main,
)

if __name__ == "__main__":
    main()
