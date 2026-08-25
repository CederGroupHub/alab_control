"""Compare the child layout of a real CallFunctionBlock against a real CallIncProgFunction."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

SOURCES = {
    "CallFunctionBlock": Path(
        r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
    ),
    "CallIncProgFunction": Path(
        r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Archive\program.xml"
    ),
}


def main() -> int:
    for tag, path in SOURCES.items():
        root = ET.parse(path).getroot()
        found = next(root.iter(tag), None)
        print(f"=== {tag} from {path.parent.name} ===")
        if found is None:
            print("  none present")
            continue
        for child in found:
            text = (child.text or "").strip()
            print(f"  <{child.tag}> {text[:60]!r}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
