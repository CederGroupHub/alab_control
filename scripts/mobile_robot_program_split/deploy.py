"""Upload the generated archives to the controller, instead of 73 trips through the UI.

Order matters. A library has to exist before a program that lists it in
``IncludeProgramFuncs`` can be opened, so the nine libraries go first and the entry
programs after. Within each group the order is irrelevant, since libraries only ever
reference each other by name.

``save_program_as`` carries the program and its canvas but not references. That is fine:
references are app-scoped and keyed by Uid, and every generated archive reuses Main's
Uids, so the split programs resolve against the references already on the controller and
share one calibration with Main rather than forking it. The ``data.xml`` beside the
archives is for the one case this does not cover: a controller that has never had Main,
where it has to be imported by hand first.

    python scripts/mobile_robot_program_split/deploy.py --dry-run
    python scripts/mobile_robot_program_split/deploy.py --only Shared Run_GoTo_BFT
    python scripts/mobile_robot_program_split/deploy.py

Nothing is uninstalled on failure. If a run stops halfway the controller holds a
partial set, which is safe because `program_mode = "main"` still routes everything
through Main; rerun once the cause is fixed, since every save overwrites.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from assignment import LIBRARIES  # noqa: E402

OUT = HERE / "split_programs"


def archives() -> list[tuple[str, Path]]:
    """Every generated archive, libraries first."""
    folders = sorted(path for path in OUT.iterdir() if path.is_dir())
    libraries = [(p.name, p) for p in folders if p.name in LIBRARIES]
    entries = [(p.name, p) for p in folders if p.name not in LIBRARIES]
    return libraries + entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default=None, help="controller address; defaults to the package's"
    )
    parser.add_argument(
        "--only", nargs="+", metavar="NAME", help="deploy just these programs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be uploaded, touching no hardware",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not OUT.is_dir():
        print(f"nothing to deploy: run generator.py first ({OUT} is missing)")
        return 1

    wanted = archives()
    if args.only:
        chosen = set(args.only)
        missing = chosen - {name for name, _ in wanted}
        if missing:
            print(f"no such archive: {', '.join(sorted(missing))}")
            return 1
        wanted = [pair for pair in wanted if pair[0] in chosen]

    print(f"{len(wanted)} archives, libraries first:")
    for name, folder in wanted:
        size = (folder / "program.xml").stat().st_size
        print(f"  {name:<40} {size / 1024:8.1f} KiB")
    if args.dry_run:
        print("\ndry run, nothing sent")
        return 0

    # Imported here so --dry-run works without the ROS dependencies installed.
    from alab_control.mobile_robot_mir250.authored_program import deploy, programming
    from alab_control.mobile_robot_mir250.clients import AbilityClient, AbilityRosClient

    ability = AbilityClient(**({"host": args.host} if args.host else {}))
    ros = AbilityRosClient(**({"host": args.host} if args.host else {}))

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
    print(f"\ndeployed {len(wanted)} programs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
