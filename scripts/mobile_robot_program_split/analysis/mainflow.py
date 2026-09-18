"""Show Main_program's four If blocks: their conditions and what each body does.

This is the preamble the generated entry programs have to reproduce, so it needs to be
read exactly rather than guessed at.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)


def describe_operand(node: ET.Element | None) -> str:
    if node is None:
        return "?"
    var = node.findtext(".//Variable/Name")
    if var:
        return f"${var.strip()}"
    value = node.findtext(".//Value")
    if value is not None:
        return repr(value.strip())
    return f"<{[c.tag for c in node]}>"


def describe_condition(condition: ET.Element | None) -> str:
    if condition is None:
        return "(none)"
    kind = (condition.findtext("Type") or "").strip()
    lhs = describe_operand(condition.find("LHS"))
    rhs = describe_operand(condition.find("RHS"))
    op = (condition.findtext("Operator") or condition.findtext("Comparator") or "").strip()
    return f"{kind}: {lhs} {op or '?'} {rhs}"


def walk(node: ET.Element, depth: int, uid_to_name: dict[str, str]) -> None:
    """Print instructions, stepping through Sequence/Instructions wrappers silently."""
    for step in node:
        if step.tag in ("Sequence", "Instructions"):
            walk(step, depth, uid_to_name)
            continue
        if step.tag in (
            "IsErrorFunctionActive",
            "ErrorFunctionName",
            "ErrorFunctionUid",
            "RetryAttempts",
        ):
            continue
        detail = ""
        target = step.findtext("FunctionBlockName")
        if target:
            detail += f" -> {uid_to_name.get(target.strip(), target.strip())!r}"
        var = step.findtext("LHS/Variable/Name") or step.findtext("Variable/Name")
        if var:
            detail += f" var={var.strip()!r}"
        rhs = step.find("RHS")
        if rhs is not None:
            detail += f" = {describe_operand(rhs)}"
        if step.tag == "If":
            detail += f"  [{describe_condition(step.find('Condition'))}]"
        print("  " * depth + step.tag + detail)
        if step.tag == "If" and depth < 6:
            for branch in ("IfBody", "ElseBody"):
                body = step.find(branch)
                if body is not None and len(body):
                    print("  " * (depth + 1) + branch + ":")
                    walk(body, depth + 2, uid_to_name)


def main() -> int:
    root = ET.parse(MAIN).getroot()
    uid_to_name = {
        (b.findtext("UID") or "").strip(): (b.findtext("Name") or "").strip()
        for b in root.iter("FunctionBlock")
    }

    wanted = sys.argv[1] if len(sys.argv) > 1 else "Main_program"
    block = next(
        b
        for b in root.iter("FunctionBlock")
        if (b.findtext("Name") or "").strip() == wanted
    )
    instructions = block.find("Body/Sequence/Instructions")
    assert instructions is not None

    if wanted != "Main_program":
        walk(instructions, 1, uid_to_name)
        return 0

    for index, node in enumerate(instructions):
        if node.tag != "If":
            continue
        print(f"--- If #{index} ---")
        print(f"  condition: {describe_condition(node.find('Condition'))}")
        for branch in ("IfBody", "ElseBody"):
            body = node.find(branch)
            if body is None or len(body) == 0:
                continue
            print(f"  {branch}:")
            walk(body, 3, uid_to_name)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
