"""Run the offline newsroom evaluation: ``python scripts/evaluate.py``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touchline_takes.evaluation import main  # pylint: disable=wrong-import-position

if __name__ == "__main__":
    sys.exit(main())
