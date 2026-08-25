"""Flatten a handler's nested If/Else chain into a list of (condition, body) branches.

The generated entry programs are built by lifting these bodies verbatim, so the
conditions have to be read exactly as the controller evaluates them.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)


def operand(node: ET.Element | None) -> str:
    if node is None:
        return "?"
    var = node.findtext("Variable/Name")
    if var:
        return f"${var.strip()}"
    value = node.findtext(".//Value")
    if value is not None:
        return repr(value.strip())
    nested = node.find("Condition")
    if nested is not None:
        return f"({condition(nested)})"
    inner = [c for c in node]
    if len(inner) == 1:
        return operand(inner[0])
    return f"<{[c.tag for c in node]}>"


def condition(node: ET.Element | None) -> str:
    if node is None:
        return "(none)"
    kind = (node.findtext("Type") or "").strip()
    if kind == "Composite":
        op = (node.findtext("LogicalOperator") or node.findtext("Operator") or "?").strip()
        return f"{operand(node.find('LHS'))} {op} {operand(node.find('RHS'))}"
    op = (node.findtext("Operator") or node.findtext("Comparator") or "?").strip()
    return f"{operand(node.find('LHS'))} {op} {operand(node.find('RHS'))}"


def calls_in(node: ET.Element, uid_to_name: dict[str, str]) -> list[str]:
    found = []
    for tag in ("CallFunctionBlock", "CallIncProgFunction"):
        for call in node.iter(tag):
            uid = (call.findtext("FunctionBlockName") or "").strip()
            found.append(uid_to_name.get(uid, uid))
    return found


def flatten(node: ET.Element, uid_to_name: dict[str, str], depth: int = 0) -> None:
    """Print an If/ElseBody chain as a flat branch list."""
    current: ET.Element | None = node
    while current is not None:
        cond = condition(current.find("Condition"))
        body = current.find("IfBody")
        calls = calls_in(body, uid_to_name) if body is not None else []
        other = (
            [c.tag for c in body if c.tag not in ("Name", "Version", "IsBlocking", "IsInitialized", "UID")]
            if body is not None
            else []
        )
        print(f"  branch  {cond}")
        print(f"      calls={calls}")
        print(f"      body tags={other}")
        else_body = current.find("ElseBody")
        if else_body is None:
            return
        nested = [c for c in else_body if c.tag == "If"]
        if not nested:
            leftover = [
                c.tag
                for c in else_body
                if c.tag not in ("Name", "Version", "IsBlocking", "IsInitialized", "UID")
            ]
            if leftover:
                print(f"  final else: {leftover} calls={calls_in(else_body, uid_to_name)}")
            return
        current = nested[0]


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "PickHandler"
    root = ET.parse(MAIN).getroot()
    uid_to_name = {
        (b.findtext("UID") or "").strip(): (b.findtext("Name") or "").strip()
        for b in root.iter("FunctionBlock")
    }
    block = next(
        b
        for b in root.iter("FunctionBlock")
        if (b.findtext("Name") or "").strip() == target
    )
    body = block.find("Body/Sequence/Instructions")
    assert body is not None

    trycatch = body.find("TryCatch")
    search_root = trycatch.find("TryBody") if trycatch is not None else body
    print(f"=== {target} ladder ===")
    ifs = [c for c in (search_root or body).iter("If")]
    if not ifs:
        print("no If found")
        return 0
    flatten(ifs[0], uid_to_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
