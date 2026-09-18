"""Work out how the canvas encodes function definitions and calls.

Three things the frontend generator needs to know:
  1. whether a canvas block id equals the program.xml UID minus its program prefix
  2. what a same-program call block looks like
  3. what a cross-program call block looks like
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation")
B = "{https://developers.google.com/blockly/xml}"
PREFIX = "Main_test_"


def fields(block: ET.Element) -> dict[str, str]:
    return {f.get("name"): (f.text or "") for f in block.findall(f"{B}field")}


def main() -> int:
    main_program = ET.parse(BASE / "Main" / "program.xml").getroot()
    uids = {
        (b.findtext("Name") or "").strip(): (b.findtext("UID") or "").strip()
        for b in main_program.iter("FunctionBlock")
    }

    front = ET.parse(BASE / "Main" / "frontend.xml").getroot()
    definitions = {}
    for block in front.findall(f"{B}block"):
        if block.get("type") != "er_function_block":
            continue
        name = fields(block).get("FunctionBlockName", "")
        definitions[name] = block

    print(f"function definitions on canvas: {len(definitions)}")
    matches = mismatches = 0
    examples = []
    for name, block in definitions.items():
        uid = uids.get(name, "")
        expected = uid[len(PREFIX):] if uid.startswith(PREFIX) else None
        if expected == block.get("id"):
            matches += 1
        else:
            mismatches += 1
            if len(examples) < 5:
                examples.append((name, block.get("id"), uid))
    print(f"  canvas id == UID without the {PREFIX!r} prefix: {matches} yes, {mismatches} no")
    for name, block_id, uid in examples:
        print(f"      {name!r} id={block_id!r} uid={uid!r}")

    # What call block types appear anywhere in the canvas?
    types = Counter(
        block.get("type")
        for block in front.iter(f"{B}block")
        if "call" in (block.get("type") or "").lower()
    )
    print(f"\ncall block types in Main: {dict(types)}")
    for call_type in types:
        sample = next(
            b for b in front.iter(f"{B}block") if b.get("type") == call_type
        )
        print(f"  {call_type}: fields={fields(sample)}")

    archive = ET.parse(BASE / "Archive" / "frontend.xml").getroot()
    print("\ncross-program call from Archive:")
    for block in archive.iter(f"{B}block"):
        if block.get("type") == "er_program":
            continue
        print(f"  type={block.get('type')} id={block.get('id')} fields={fields(block)}")

    # How is the Main_program definition body nested?
    entry = definitions.get("Main_program")
    if entry is not None:
        print("\nMain_program canvas nesting:")
        statements = entry.findall(f"{B}statement")
        print(f"  statements: {[s.get('name') for s in statements]}")
        for statement in statements:
            first = statement.find(f"{B}block")
            chain = 0
            cursor = first
            kinds = []
            while cursor is not None:
                chain += 1
                kinds.append(cursor.get("type"))
                nxt = cursor.find(f"{B}next")
                cursor = nxt.find(f"{B}block") if nxt is not None else None
            print(f"  '{statement.get('name')}' chain length {chain}")
            print(f"    {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
