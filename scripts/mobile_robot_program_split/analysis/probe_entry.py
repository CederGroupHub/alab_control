"""Print a generated entry program's chain, both files side by side."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from generator import B, front_chain  # noqa: E402

OUT = HERE.parent / "split_programs"


def label(node: ET.Element) -> str:
    program = (node.findtext("ProgramName") or "").strip()
    if program:
        return f"{node.tag} -> {program}"
    if node.tag == "If":
        variable = node.findtext("Condition/LHS/Variable/Name")
        operator = node.findtext("Condition/Operator")
        value = node.findtext("Condition/RHS/ValueFixed/Value")
        thrown = [t.findtext("Message/ValueFixed/Value") for t in node.iter("Throw")]
        return f"If {variable} {operator} {value!r} -> throw {thrown}"
    return node.tag


def main() -> None:
    for name in sys.argv[1:]:
        root = ET.parse(OUT / name / "program.xml").getroot()
        instructions = root.find("FunctionBlock/Body/Sequence/Instructions")
        front = ET.parse(OUT / name / "frontend.xml").getroot()
        entry = next(
            b
            for b in front.findall(f"{B}block")
            if b.get("type") == "er_function_block"
        )
        canvas = front_chain(entry.find(f"{B}statement"))
        print(f"== {name}")
        for node, block in zip(list(instructions), canvas):
            print(f"   {label(node):<70} | {block.get('type')}")
        if len(list(instructions)) != len(canvas):
            print(f"   MISALIGNED: {len(list(instructions))} vs {len(canvas)}")


if __name__ == "__main__":
    main()
