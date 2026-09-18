"""Compare Program elements and their er_program canvas blocks across both exports."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation")
BLOCKLY = "{https://developers.google.com/blockly/xml}"


def main() -> int:
    for label in ("Main", "Archive"):
        print(f"===== {label}")
        program_xml = BASE / label / "program.xml"
        for program in ET.parse(program_xml).getroot().iter("Program"):
            name = (program.findtext("Name") or "").strip()
            uid = (program.findtext("UID") or "").strip()
            includes = (program.findtext("IncludeProgramFuncs") or "").strip()
            count = len(list(program.find("Instructions") or []))
            print(
                f"  Program name={name!r} uid={uid!r} instructions={count} "
                f"includes={includes!r}"
            )

        frontend = BASE / label / "frontend.xml"
        if not frontend.is_file():
            continue
        root = ET.parse(frontend).getroot()
        types = Counter(
            block.get("type") for block in root.findall(f"{BLOCKLY}block")
        )
        print(f"  top-level canvas block types: {dict(types)}")
        for block in root.findall(f"{BLOCKLY}block"):
            if block.get("type") != "er_program":
                continue
            fields = {
                f.get("name"): (f.text or "")
                for f in block.findall(f"{BLOCKLY}field")
            }
            statements = [s.get("name") for s in block.findall(f"{BLOCKLY}statement")]
            print(
                f"  er_program id={block.get('id')!r} "
                f"_progName={fields.get('_progName','')[:50]!r} "
                f"statements={statements}"
            )
        # How are functions represented on the canvas?
        function_blocks = [
            block
            for block in root.findall(f"{BLOCKLY}block")
            if block.get("type", "").startswith("er_function")
        ]
        print(f"  er_function* top-level blocks: {len(function_blocks)}")
        for block in function_blocks[:3]:
            fields = {
                f.get("name"): (f.text or "")
                for f in block.findall(f"{BLOCKLY}field")
            }
            print(f"      id={block.get('id')!r} type={block.get('type')} fields={fields}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
