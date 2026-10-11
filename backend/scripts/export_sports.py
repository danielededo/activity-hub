"""Write the sport catalogue as the API serves it, for the frontend tests.

The frontend tests run without a server, so they read the catalogue from
frontend/tests/sports.json. Run this after changing app/services/sports.py;
tests/test_sports.py fails until you do. Needs no database.

    python -m scripts.export_sports
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.schemas.sport import SportRead
from app.services.sports import SPORTS

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "frontend" / "tests" / "sports.json"


def catalogue_json() -> str:
    """The catalogue exactly as GET /api/sports returns it."""
    sports = [SportRead.model_validate(sport).model_dump() for sport in SPORTS]
    return json.dumps(sports, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.write_text(catalogue_json())
    print(f"Wrote {len(SPORTS)} sports to {args.out}")


if __name__ == "__main__":
    main()
