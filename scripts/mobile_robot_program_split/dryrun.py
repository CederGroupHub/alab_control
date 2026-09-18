"""Resolve every route MobileRobotHelper can ask for, without touching hardware.

The eight ``pick_*`` methods on ``RobotArmMobile`` validate their arguments and then call
``move_robot_arm`` with a region/slot pair each. Those pairs, and the base targets the
task uses, are the whole vocabulary AlabOS can produce. This walks all of it through the
routing table and the generated archives, so a route with no program, or a program that
was never generated, shows up here rather than on the cell.

Named tuples of literal strings rather than an import, because alab_control cannot import
alab_one. If a ``pick_*`` signature changes, this list has to change with it.

    python scripts/mobile_robot_program_split/dryrun.py            # summary
    python scripts/mobile_robot_program_split/dryrun.py --verbose  # every route
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from alab_control.mobile_robot_arm import programs as P  # noqa: E402

OUT = HERE / "split_programs"

SUBRACKS = ("SubRackA", "SubRackB", "SubRackC", "SubRackD")
VERTICAL = tuple(name + "Vertical" for name in SUBRACKS)
CRUCIBLES = tuple(str(n) for n in range(1, 5))
GRID = tuple(str(n) for n in range(1, 17))

#: Base targets mobile_robot_helper.py and _soak_test ask for, plus the two the device
#: reaches through charge() and charge_no_waiting() rather than move_base_to().
BASE_TARGETS = ("Home", "LABMAN", "BFT", "DASH", "SRS", "Charging", "ChargingNoWait")


def transfers() -> list[tuple[str, tuple[str, str, str, str]]]:
    """(method, (source_region, source_slot, destination_region, destination_slot))."""
    out: list[tuple[str, tuple[str, str, str, str]]] = []
    for source in SUBRACKS:
        for destination in SUBRACKS:
            out.append(
                ("pick_subrack_from_LABMAN_to_ROBOT_BASE",
                 ("LABMAN", source, "ROBOT_BASE", destination))
            )
            out.append(
                ("pick_subrack_from_ROBOT_BASE_to_LABMAN",
                 ("ROBOT_BASE", source, "LABMAN", destination))
            )
    for source in SUBRACKS:
        # The SRS methods add the Vertical suffix themselves.
        for destination in VERTICAL:
            out.append(
                ("pick_subrack_from_SRS_to_ROBOT_BASE",
                 ("SRS", source, "ROBOT_BASE", destination))
            )
        for vertical in VERTICAL:
            out.append(
                ("pick_subrack_from_ROBOT_BASE_to_SRS",
                 ("ROBOT_BASE", vertical, "SRS", source))
            )
    for station in ("BFT", "DASH"):
        for subrack in SUBRACKS:
            for crucible in CRUCIBLES:
                for slot in GRID:
                    out.append(
                        (f"pick_crucible_from_ROBOT_BASE_to_{station}",
                         (f"ROBOT_BASE/{subrack}", crucible, station, slot))
                    )
                    out.append(
                        (f"pick_crucible_from_{station}_to_ROBOT_BASE",
                         (station, slot, f"ROBOT_BASE/{subrack}", crucible))
                    )
    return out


def installed() -> set[str]:
    return {path.name for path in OUT.iterdir() if path.is_dir()} if OUT.is_dir() else set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    present = installed()
    used: set[str] = set()
    failures: list[str] = []

    print("=== base moves: every start against every target the task asks for ===")
    starts = sorted(set(P.BASE_POSITIONS) | {P.UNKNOWN, "FurnaceWorkbenchCalibrationForMoving"})
    for start in starts:
        for target in BASE_TARGETS:
            try:
                steps = P.resolve_base_move(start, target)
            except P.UnsupportedRoute as error:
                failures.append(f"base {start} -> {target}: {error}")
                continue
            used.update(name for name, _ in steps)
            if args.verbose:
                names = " then ".join(name for name, _ in steps) or "(already there)"
                print(f"  {start:>38} -> {target:<8} {names}")
    print(f"  {len(starts)} start positions x {len(BASE_TARGETS)} targets, "
          f"{len(failures)} unroutable")

    print("\n=== arm transfers: every pick_* argument combination ===")
    routes = transfers()
    for method, (source_region, source_slot, destination_region, destination_slot) in routes:
        for resolve, region, slot, what in (
            (P.resolve_pick, source_region, source_slot, "pick"),
            (P.resolve_place, destination_region, destination_slot, "place"),
        ):
            try:
                program, arguments = resolve(region, slot)
            except P.UnsupportedRoute as error:
                failures.append(f"{method}: {error}")
                continue
            used.add(program)
            if args.verbose:
                print(f"  {method:<42} {what:<5} {region:>22}/{slot:<20} {program}")
    print(f"  {len(routes)} transfers, {len(routes) * 2} resolutions")

    print(f"\ndistinct programs reached: {len(used)}")
    if present:
        not_generated = sorted(used - present)
        print(f"archives on disk: {len(present)}")
        print(f"reached but never generated: {not_generated or 'none'}")
        if not_generated:
            failures.extend(f"no archive for {name}" for name in not_generated)
        unreached = sorted(set(P.ENTRY_PROGRAMS) - used)
        print(f"generated but not reachable from AlabOS: {len(unreached)}")
        for name in unreached:
            print(f"    {name}")
    else:
        print(f"no archives on disk at {OUT}; run generator.py to check coverage")

    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for line in failures[:40]:
            print(f"  {line}")
        return 1
    print("\nevery route AlabOS can ask for resolves to a generated program")
    return 0


if __name__ == "__main__":
    sys.exit(main())
