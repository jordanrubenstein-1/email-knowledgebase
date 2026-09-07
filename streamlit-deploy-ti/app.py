"""TI Lifecycle Dashboard — Streamlit Cloud entry point.

Streamlit Cloud requires the main file to be in the same directory as
requirements.txt, so this thin wrapper delegates to the real dashboard at
scripts/ti_lifecycle_dashboard.py.

To deploy on Streamlit Cloud:
  Repository: this repo
  Branch:     main
  Main file:  streamlit-deploy-ti/app.py
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

_src = _root / "scripts" / "ti_lifecycle_dashboard.py"
exec(  # noqa: S102
    compile(_src.read_text("utf-8"), str(_src), "exec"),
    {"__file__": str(_src), "__name__": "__main__"},
)
