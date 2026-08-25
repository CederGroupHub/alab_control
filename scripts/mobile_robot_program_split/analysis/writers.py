"""Which functions write the base/arm state variables, and where they land after the split."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from assignment import ASSIGNMENT  # noqa: E402

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)
TARGETS = ("BasePosition", "RobotPose", "robot_arm_region", "robot_arm_slot")


def main() -> int:
    root = ET.parse(MAIN).getroot()
    parent_of = {child: parent for parent in root.iter() for child in parent}

    def owner(node: ET.Element) -> str:
        cursor = node
        while cursor is not None:
            if cursor.tag in ("FunctionBlock", "Program"):
                return (cursor.findtext("Name") or "?").strip()
            cursor = parent_of.get(cursor)
        return "<top level>"

    for target in TARGETS:
        writers: set[tuple[str, str]] = set()
        for tag in ("SaveVariable", "Assign"):
            for node in root.iter(tag):
                name = node.findtext("Variable/Name") or node.findtext(
                    "LHS/Variable/Name"
                )
                if name and name.strip() == target:
                    writers.add((tag, owner(node)))
        print(f"== {target}: {len(writers)} writes")
        for tag, fn in sorted(writers, key=lambda pair: (pair[1], pair[0])):
            lib = ASSIGNMENT.get(fn, "?")
            print(f"   {tag:<13} {lib:<16} {fn}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
