"""Prove the split works on the real controller before uploading all 73 programs.

Two things in the split have no precedent in ``Main``: it never used
``CallIncProgFunction``, so nothing in the export shows whether a call into another
program's functions behaves as expected, and the argument dictionary now arrives in an
entry program rather than in ``Main`` itself. Both are all-or-nothing. So run one real
movement first.

The test deploys the nine libraries and a single entry program, runs it, and then reads
the controller's own variables back to check what happened. ``Run_GoTo_Home`` is the
default because it is the one base move with no station to back out of, and because it is
short when the robot is already home -- which this refuses to run without.

An unused argument carries a marker. A base move never reads ``source_region``, but the
inlined preamble still materialises and saves it, so finding the marker afterwards is
proof that the entry program could read its own arguments.

    python scripts/mobile_robot_program_split/smoketest.py --dry-run
    python scripts/mobile_robot_program_split/smoketest.py
    python scripts/mobile_robot_program_split/smoketest.py --program Run_GoTo_Charging

Nothing here is destructive, but it does move the base. Watch the cell.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from assignment import LIBRARIES  # noqa: E402
from deploy import OUT, archives  # noqa: E402

from alab_control.mobile_robot_arm import programs as P  # noqa: E402

MARKER_ARGUMENT = "source_region"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None, help="controller address")
    parser.add_argument(
        "--program",
        default=P.GOTO[P.HOME],
        help="the entry program to prove; must be a base move",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the plan, touch no hardware"
    )
    parser.add_argument(
        "--from-anywhere",
        action="store_true",
        help="skip the check that the base is already home",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not OUT.is_dir():
        print(f"nothing to deploy: run generator.py first ({OUT} is missing)")
        return 1
    if args.program not in P.GOTO.values():
        print(
            f"{args.program} is not a base move. Pick one of: "
            f"{', '.join(sorted(P.GOTO.values()))}"
        )
        return 1

    wanted = [pair for pair in archives() if pair[0] in LIBRARIES]
    wanted += [pair for pair in archives() if pair[0] == args.program]
    if len(wanted) != len(LIBRARIES) + 1:
        print(f"expected {len(LIBRARIES)} libraries and {args.program}, found {len(wanted)}")
        return 1

    marker = f"SMOKE-{int(time.time())}"
    target = next(pose for pose, program in P.GOTO.items() if program == args.program)
    arguments = P.arguments(target_base_position=target)
    arguments[MARKER_ARGUMENT] = marker

    print(f"{len(wanted)} programs, libraries first:")
    for name, _ in wanted:
        print(f"  {name}")
    print(f"\nthen run {args.program} with {arguments}")
    print(f"then read {MARKER_ARGUMENT} and BasePosition back over ROS")
    if args.dry_run:
        print("\ndry run, nothing sent")
        return 0

    # Imported here so --dry-run needs none of the hardware dependencies.
    from alab_control.mobile_robot_arm import MobileRobotArm
    from alab_control.mobile_robot_mir250.authored_program import deploy, programming
    from alab_control.mobile_robot_mir250.clients import AbilityClient, AbilityRosClient

    where = {"host": args.host} if args.host else {}
    ability = AbilityClient(**where)
    ros = AbilityRosClient(**where)

    before = ros.base_position()
    print(f"\ncontroller says the base is at {before!r}")
    if before != P.HOME and not args.from_anywhere:
        print(
            f"refusing to drive home from {before!r}: leaving a station is its own "
            f"movement, and this test is meant to be a short one. Move the base home "
            f"first, or pass --from-anywhere if you know the path is clear."
        )
        return 1

    print()
    with programming(ros, ability) as session:
        for index, (name, folder) in enumerate(wanted, start=1):
            deploy(
                session,
                name,
                (folder / "program.xml").read_text(encoding="utf-8"),
                (folder / "frontend.xml").read_text(encoding="utf-8"),
            )
            print(f"  [{index:>2}/{len(wanted)}] {name}")

    print(f"\nrunning {args.program}")
    MobileRobotArm(**({"ip": args.host} if args.host else {})).run_program(
        args.program, arguments
    )

    print("\nwhat the controller has now:")
    seen = ros.variable(MARKER_ARGUMENT)
    after = ros.base_position()
    print(f"  {MARKER_ARGUMENT:<20} {seen!r}")
    print(f"  {'BasePosition':<20} {after!r}")

    failures = []
    if seen != marker:
        failures.append(
            f"the entry program did not read its own arguments: {MARKER_ARGUMENT} is "
            f"{seen!r}, not {marker!r}. The preamble either did not run or could not see "
            f"the argument dictionary."
        )
    if after != target:
        failures.append(
            f"BasePosition is {after!r}, not {target!r}. The movement ran but did not "
            f"leave the controller believing it is where it should be."
        )

    if failures:
        print("\nFAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nsmoke test passed: arguments arrive, cross-program calls run, base moved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
