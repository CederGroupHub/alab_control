"""How er_controls_if encodes its branches, and whether the canvas mirrors program.xml.

The generator pairs instructions positionally between the two files, so any place the
chain lengths disagree is a place the pairing would silently misalign.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from routes_from_xml import load  # noqa: E402

BASE = Path(r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation")
B = "{https://developers.google.com/blockly/xml}"


def fields(block: ET.Element) -> dict[str, str]:
    return {f.get("name"): (f.text or "") for f in block.findall(f"{B}field")}


def chain(statement: ET.Element | None) -> list[ET.Element]:
    if statement is None:
        return []
    out = []
    cursor = statement.find(f"{B}block")
    while cursor is not None:
        out.append(cursor)
        nxt = cursor.find(f"{B}next")
        cursor = nxt.find(f"{B}block") if nxt is not None else None
    return out


def main() -> int:
    _, uid_to_name, by_name = load()
    front = ET.parse(BASE / "Main" / "frontend.xml").getroot()
    definitions = {
        fields(block).get("FunctionBlockName", ""): block
        for block in front.findall(f"{B}block")
        if block.get("type") == "er_function_block"
    }

    # Do the canvas chain and the program.xml instruction list line up, per function?
    mismatched = []
    for name, block in definitions.items():
        xml_block = by_name.get(name)
        if xml_block is None:
            continue
        instructions = xml_block.find("Body/Sequence/Instructions")
        expected = len(list(instructions)) if instructions is not None else 0
        actual = len(chain(block.find(f"{B}statement")))
        if expected != actual:
            mismatched.append((name, expected, actual))
    print(f"functions compared: {len(definitions)}")
    print(f"chain length mismatches: {len(mismatched)}")
    for name, expected, actual in mismatched[:10]:
        print(f"    {name!r}: program.xml {expected} vs canvas {actual}")

    # Shape of an if block, taken from BaseHandler.
    base = definitions["BaseHandler"]
    top = chain(base.find(f"{B}statement"))
    print(f"\nBaseHandler canvas chain: {[b.get('type') for b in top]}")
    node = top[0]
    depth = 0
    while node is not None and depth < 4:
        statements = [s.get("name") for s in node.findall(f"{B}statement")]
        values = [v.get("name") for v in node.findall(f"{B}value")]
        mutation = node.find(f"{B}mutation")
        print(
            f"  depth {depth}: type={node.get('type')} "
            f"mutation={dict(mutation.attrib) if mutation is not None else None} "
            f"values={values} statements={statements}"
        )
        do0 = node.find(f'{B}statement[@name="DO0"]')
        inner = chain(do0)
        print(f"      DO0 chain: {[b.get('type') for b in inner]}")
        else_statement = node.find(f'{B}statement[@name="ELSE"]')
        nxt = chain(else_statement)
        node = nxt[0] if nxt else None
        depth += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
