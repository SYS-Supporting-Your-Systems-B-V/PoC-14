import os
import sys
from pathlib import Path

# Use a test-specific env profile before importing the app module.
os.environ.setdefault("MCSD_ENV_FILE", ".env.pytest")

# Ensure project root (containing app/main.py) is importable.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
