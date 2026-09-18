"""Map every variable to the functions that touch it.

Used to check that splitting functions across programs cannot strand a variable:
a Global=1 variable is controller-wide and safe, but a Global=0 (function-local)
one is only safe if every function touching it lands in the same program.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)
FOCUS = "FurnaceStationTag"


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

    # Every <Variable><Name> reference anywhere, attributed to its function.
    users: dict[str, set[str]] = defaultdict(set)
    for var in root.iter("Variable"):
        name = (var.findtext("Name") or "").strip()
        if name:
            users[name].add(owner(var))

    print(f"distinct variables referenced: {len(users)}")

    shared = {v: fns for v, fns in users.items() if len(fns) > 1}
    print(f"variables touched by more than one function: {len(shared)}")

    print(f"\nfunctions touching {FOCUS!r}:")
    for fn in sorted(users.get(FOCUS, ())):
        print(f"    {fn}")

    print("\ntop shared variables (by function count):")
    for name, fns in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f"    {name:<34} {len(fns)} functions")

    out = Path(__file__).with_name("varmap.json")
    out.write_text(
        json.dumps({v: sorted(f) for v, f in sorted(users.items())}, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
