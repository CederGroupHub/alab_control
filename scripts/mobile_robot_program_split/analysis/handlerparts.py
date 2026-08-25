"""The pieces of PickHandler / PlaceHandler that have to become Shared helpers."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from routes_from_xml import leaf_calls, load, steps  # noqa: E402


def show(label: str, node: ET.Element | None, uid_to_name) -> None:
    if node is None:
        print(f"  {label}: absent")
        return
    inner = steps(node)
    print(f"  {label}: {[c.tag for c in inner]}")
    print(f"      calls: {leaf_calls(node, uid_to_name)}")


def main() -> int:
    _, uid_to_name, by_name = load()
    for handler in ("PickHandler", "PlaceHandler"):
        block = by_name[handler]
        instructions = block.find("Body/Sequence/Instructions")
        children = list(instructions)
        print(f"=== {handler}: {[c.tag for c in children]}")
        trycatch = instructions.find("TryCatch")
        show("TryBody", trycatch.find("TryBody"), uid_to_name)
        show("CatchBody", trycatch.find("CatchBody"), uid_to_name)
        print(f"  NumberOfTries: {trycatch.findtext('NumberOfTries')!r}")
        index = children.index(trycatch)
        trailing = children[index + 1 :]
        print(f"  after the TryCatch: {[c.tag for c in trailing]}")
        for node in trailing:
            print(f"      {node.tag} calls={leaf_calls(node, uid_to_name)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
