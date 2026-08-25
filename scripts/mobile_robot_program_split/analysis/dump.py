"""Print the instruction tree of named functions, shallowly, to see their shape."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)
# Leaf-ish tags whose innards are noise for this purpose.
SKIP_CHILDREN = {"Name", "Version", "UID", "IsInitialized", "Description"}


def show(node: ET.Element, depth: int, limit: int, uid_to_name: dict[str, str]) -> None:
    if depth > limit:
        return
    label = node.tag
    text = (node.text or "").strip()
    extras = []
    name = node.findtext("Name")
    if name and name.strip() != node.tag:
        extras.append(f"name={name.strip()!r}")
    target = node.findtext("FunctionBlockName")
    if target:
        extras.append(f"-> {uid_to_name.get(target.strip(), target.strip())!r}")
    var = node.findtext("Variable/Name") or node.findtext("LHS/Variable/Name")
    if var:
        extras.append(f"var={var.strip()!r}")
    key = node.findtext("Key") or node.findtext("Key/ValueFixed/Value")
    if key:
        extras.append(f"key={key.strip()!r}")
    if text and node.tag not in ("Name",):
        extras.append(f"text={text[:40]!r}")
    print("  " * depth + label + ("  " + " ".join(extras) if extras else ""))
    if node.tag in SKIP_CHILDREN:
        return
    for child in node:
        if child.tag in SKIP_CHILDREN:
            continue
        show(child, depth + 1, limit, uid_to_name)


def main() -> int:
    import os

    targets = sys.argv[1:] or ["Main_program"]
    limit = int(os.environ.get("DEPTH", "4"))
    root = ET.parse(MAIN).getroot()
    uid_to_name = {
        (b.findtext("UID") or "").strip(): (b.findtext("Name") or "").strip()
        for b in root.iter("FunctionBlock")
    }
    for block in root.iter("FunctionBlock"):
        name = (block.findtext("Name") or "").strip()
        if name not in targets:
            continue
        print(f"===== {name} (UID {block.findtext('UID')}) =====")
        print(f"  direct children: {[c.tag for c in block]}")
        body = block.find("Instructions")
        if body is None:
            for c in block:
                if c.tag not in SKIP_CHILDREN:
                    show(c, 1, limit, uid_to_name)
        else:
            for instruction in body:
                show(instruction, 1, limit, uid_to_name)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
