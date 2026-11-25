"""Copy one stage of the documentation into docs/index.html."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = {"1": "1-baseline.html", "2": "2-cosmetic.html", "3": "3-account-id.html"}

if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
    print("Usage: python scripts/publish_stage.py 1|2|3")
    sys.exit(2)

shutil.copyfile(ROOT / "stages" / STAGES[sys.argv[1]], ROOT / "docs" / "index.html")
print(f"docs/index.html now holds stage {sys.argv[1]}. Commit and push it, then run "
      "scripts/check_live_page.py until the new text shows.")
