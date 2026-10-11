"""Re-apply the sport catalogue to activities already stored.

A sport added to app/services/sports.py, or an alias added to one, only applies
to files uploaded from then on. This re-reads what each stored activity's file
declared — kept in its raw_data for this purpose — and moves the activity to
the sport the catalogue now gives it. Strength sessions stored before strength
existed, for instance, move from "other" to "strength".

    python -m scripts.backfill_sports            # apply
    python -m scripts.backfill_sports --dry-run  # only report what would move

Safe to re-run: an activity already in the right sport is left alone. FIT
activities stored before the declared sport was kept can only be moved by
their sub-sport, which is how strength is recognised anyway.

An activity still carrying the name the parser gave it ("Other 2026-05-04") is
renamed along with it. A name that came from the file, or one you chose, stays.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Workout
from app.services.sports import sport_from_file, sport_from_fit_sub_sport

#: Where each parser keeps what the file called its sport.
DECLARED = {"fit": "declared_sport", "tcx": "declared_sport", "gpx": "declared_type"}


@dataclass(slots=True)
class Outcome:
    considered: int = 0
    #: (from, to) → how many activities moved that way.
    moved: Counter = field(default_factory=Counter)
    renamed: int = 0


def sport_for(workout: Workout) -> str | None:
    """The sport the catalogue gives this activity now, or None if it cannot say."""
    raw = workout.raw_data or {}
    key = DECLARED.get(workout.file_format)
    if key is None:
        return None
    if key in raw:
        return sport_from_file(workout.file_format, raw[key], raw.get("sub_sport"))
    if workout.file_format == "fit":
        # Stored before the declared sport was kept: the sub-sport is all there is.
        return sport_from_fit_sub_sport(raw.get("sub_sport"))
    return None


def _generated_name(sport: str, workout: Workout) -> str:
    """The name the FIT and TCX parsers give an activity whose file names none."""
    return f"{sport.capitalize()} {workout.start_time.date().isoformat()}"


def backfill(db: Session, *, dry_run: bool = False) -> Outcome:
    outcome = Outcome()
    for workout in db.scalars(select(Workout).order_by(Workout.id)):
        outcome.considered += 1
        target = sport_for(workout)
        if target is None or target == workout.sport_type:
            continue

        outcome.moved[(workout.sport_type, target)] += 1
        if workout.name == _generated_name(workout.sport_type, workout):
            outcome.renamed += 1
            if not dry_run:
                workout.name = _generated_name(target, workout)
        if not dry_run:
            workout.sport_type = target

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would move, change nothing"
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        try:
            outcome = backfill(db, dry_run=args.dry_run)
        except SQLAlchemyError as exc:
            print(f"Could not reach the database: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    verb = "would move" if args.dry_run else "moved"
    print(f"{outcome.considered} activities considered")
    for (before, after), count in sorted(outcome.moved.items()):
        print(f"  {count} {verb} from {before} to {after}")
    if not outcome.moved:
        print("  all already in the right sport")
    print(f"  {outcome.renamed} {'would be ' if args.dry_run else ''}renamed")


if __name__ == "__main__":
    main()
