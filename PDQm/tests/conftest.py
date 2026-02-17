import os
import sys
from pathlib import Path

# Ensure project root (containing app/) is importable when tests are run from any cwd.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default test DB to local SQLite so pytest does not depend on external MSSQL connectivity.
# If PDQM_DB_URL is already set in the shell, keep that value.
db_path = (ROOT / "pdqm.db").resolve().as_posix()
os.environ.setdefault("PDQM_DB_URL", f"sqlite:///{db_path}")
