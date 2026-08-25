"""How the canvas encodes the base ladder: nested ELSE blocks, or flat elseif slots?"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from routes_from_xml import load, steps  # noqa: E402

BASE = Path(r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation")
B = "{https://developers.google.com/blockly/xml}"


def fields_of(block):
    return {f.get("name"): (f.text or "") for f in block.findall(f"{B}field")}


def chain(statement):
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
        fields_of(b).get("FunctionBlockName", ""): b
        for b in front.findall(f"{B}block")
        if b.get("type") == "er_function_block"
    }

    base = definitions["BaseHandler"]
    outer = chain(base.find(f"{B}statement"))[0]
    guard = chain(outer.find(f'{B}statement[@name="DO0"]'))
    print(f"guard blocks: {[b.get('type') for b in guard]}")

    for label, block in (("leave-guard", guard[0]), ("goto-ladder", guard[1])):
        mutation = block.find(f"{B}mutation")
        statements = [s.get("name") for s in block.findall(f"{B}statement")]
        values = [v.get("name") for v in block.findall(f"{B}value")]
        print(f"\n{label}: mutation={dict(mutation.attrib) if mutation is not None else None}")
        print(f"  values={values}")
        print(f"  statements={statements}")
        for name in statements:
            inner = chain(block.find(f'{B}statement[@name="{name}"]'))
            print(f"    {name}: {[b.get('type') for b in inner]}")

    # And the program.xml side of the goto ladder for comparison.
    xml_base = by_name["BaseHandler"].find("Body/Sequence/Instructions")
    outer_xml = list(xml_base)[0]
    guard_xml = [n for n in steps(outer_xml.find("IfBody")) if n.tag == "If"]
    print(f"\nprogram.xml guard Ifs: {len(guard_xml)}")
    node = guard_xml[1]
    depth = 0
    while node is not None and depth < 3:
        body = steps(node.find("IfBody"))
        else_body = steps(node.find("ElseBody")) if node.find("ElseBody") is not None else []
        print(f"  depth {depth}: IfBody={[c.tag for c in body]} ElseBody={[c.tag for c in else_body]}")
        nested = [c for c in else_body if c.tag == "If"]
        node = nested[0] if nested else None
        depth += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
