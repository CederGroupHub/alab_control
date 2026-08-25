"""Extract the authoritative route table straight out of the handler ladders.

Rather than transcribing the ladders by hand, walk them: for every branch, record the
condition and the leaf function it ends up calling. The generator uses this to lift
branch bodies verbatim, and the result is diffed against the hand-written table in
alab_control.mobile_robot_arm.programs so the two cannot drift apart.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: The exported Main archive everything here reads. Not in the repo -- it is a 48k-line
#: vendor export, and the point of the split is to stop editing it. Set MAIN_EXPORT to
#: the folder holding program.xml, frontend.xml and data.xml on another machine.
MAIN_DIR = Path(
    os.environ.get(
        "MAIN_EXPORT",
        r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main",
    )
)
MAIN = MAIN_DIR / "program.xml"
NOISE = {"Name", "Version", "IsBlocking", "IsInitialized", "UID", "Description"}


def load() -> tuple[ET.Element, dict[str, str], dict[str, ET.Element]]:
    root = ET.parse(MAIN).getroot()
    uid_to_name: dict[str, str] = {}
    by_name: dict[str, ET.Element] = {}
    for block in root.iter("FunctionBlock"):
        name = (block.findtext("Name") or "").strip()
        uid = (block.findtext("UID") or "").strip()
        if name:
            by_name[name] = block
            if uid:
                uid_to_name[uid] = name
    return root, uid_to_name, by_name


def compare_parts(node: ET.Element | None) -> tuple[str, str, str] | None:
    """(variable, operator, literal) for a simple Compare condition."""
    if node is None:
        return None
    if (node.findtext("Type") or "").strip() != "Compare":
        return None
    var = node.findtext("LHS/Variable/Name")
    literal = node.find("RHS")
    value = literal.findtext(".//Value") if literal is not None else None
    operator = (node.findtext("Operator") or node.findtext("Comparator") or "").strip()
    if var is None or value is None:
        return None
    return var.strip(), operator, value.strip()


def composite_values(node: ET.Element | None) -> list[tuple[str, str, str]]:
    """Every simple Compare inside a possibly-composite condition."""
    if node is None:
        return []
    simple = compare_parts(node)
    if simple:
        return [simple]
    out: list[tuple[str, str, str]] = []
    for side in ("LHS", "RHS"):
        child = node.find(side)
        if child is None:
            continue
        for nested in child.iter("Condition"):
            out.extend(composite_values(nested))
        inner = compare_parts(child.find("Condition")) if child.find("Condition") is not None else None
        if inner:
            out.append(inner)
    # De-duplicate, keep order.
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


WRAPPERS = ("Sequence", "Instructions")
SEQUENCE_META = (
    "IsErrorFunctionActive",
    "ErrorFunctionName",
    "ErrorFunctionUid",
    "RetryAttempts",
)


def steps(node: ET.Element | None) -> list[ET.Element]:
    """The real instructions of a body, stepping through Sequence/Instructions wrappers."""
    if node is None:
        return []
    out: list[ET.Element] = []
    for child in node:
        if child.tag in WRAPPERS:
            out.extend(steps(child))
        elif child.tag not in NOISE and child.tag not in SEQUENCE_META:
            out.append(child)
    return out


def chain(if_node: ET.Element):
    """Yield (conditions, IfBody) for an If/ElseBody chain, plus the trailing else."""
    current: ET.Element | None = if_node
    while current is not None:
        yield composite_values(current.find("Condition")), current.find("IfBody")
        else_body = current.find("ElseBody")
        if else_body is None:
            return
        nested = [c for c in steps(else_body) if c.tag == "If"]
        if not nested:
            leftover = steps(else_body)
            if leftover:
                yield None, else_body
            return
        current = nested[0]


def first_if(node: ET.Element | None) -> ET.Element | None:
    if node is None:
        return None
    for child in node:
        if child.tag == "If":
            return child
        if child.tag in ("Sequence", "Instructions"):
            found = first_if(child)
            if found is not None:
                return found
    return None


def leaf_calls(node: ET.Element | None, uid_to_name: dict[str, str]) -> list[str]:
    if node is None:
        return []
    names = []
    for tag in ("CallFunctionBlock", "CallIncProgFunction"):
        for call in node.iter(tag):
            uid = (call.findtext("FunctionBlockName") or "").strip()
            names.append(uid_to_name.get(uid, uid))
    return names


def arm_ladder(handler: str, by_name) -> ET.Element | None:
    """The outermost If of a pick/place handler's dispatch ladder."""
    block = by_name[handler]
    body = block.find("Body/Sequence/Instructions")
    trycatch = body.find("TryCatch") if body is not None else None
    scope = trycatch.find("TryBody") if trycatch is not None else body
    return first_if(scope)


def arm_branches(handler: str, uid_to_name, by_name) -> list[dict]:
    """Every (region, slot) branch of a handler, with the body element to lift."""
    outer = arm_ladder(handler, by_name)
    if outer is None:
        return []

    routes: list[dict] = []
    for conditions, region_body in chain(outer):
        if conditions is None or region_body is None:
            continue
        region = next((v for var, _, v in conditions if "region" in var), None)
        if region is None:
            continue
        inner = first_if(region_body)
        if inner is None:
            routes.append(
                {
                    "region": region,
                    "slot": None,
                    "calls": leaf_calls(region_body, uid_to_name),
                    "body": region_body,
                }
            )
            continue
        for slot_conditions, slot_body in chain(inner):
            if slot_conditions is None or slot_body is None:
                continue
            slot = next((v for var, _, v in slot_conditions if "slot" in var), None)
            routes.append(
                {
                    "region": region,
                    "slot": slot,
                    "calls": leaf_calls(slot_body, uid_to_name),
                    "body": slot_body,
                }
            )
    return routes


def arm_routes(handler: str, root: ET.Element, uid_to_name, by_name) -> list[dict]:
    """arm_branches without the elements, so the result can be serialised."""
    return [
        {k: v for k, v in branch.items() if k != "body"}
        for branch in arm_branches(handler, uid_to_name, by_name)
    ]


def base_branches(uid_to_name, by_name) -> dict[str, list[dict]]:
    block = by_name["BaseHandler"]
    body = block.find("Body/Sequence/Instructions")
    outer = first_if(body)
    assert outer is not None
    guard = outer.find("IfBody")
    assert guard is not None

    inner_ifs = [c for c in steps(guard) if c.tag == "If"]
    leave: list[dict] = []
    goto: list[dict] = []

    if inner_ifs:
        leave_guard = inner_ifs[0]
        leave_chain_root = first_if(leave_guard.find("IfBody"))
        if leave_chain_root is not None:
            for conditions, branch in chain(leave_chain_root):
                if branch is None:
                    continue
                values = [v for var, _, v in (conditions or []) if var == "BasePosition"]
                leave.append(
                    {
                        "from": values,
                        "calls": leaf_calls(branch, uid_to_name),
                        "tags": [c.tag for c in branch if c.tag not in NOISE],
                        "body": branch,
                    }
                )
    if len(inner_ifs) > 1:
        for conditions, branch in chain(inner_ifs[1]):
            if branch is None:
                continue
            values = [
                v for var, _, v in (conditions or []) if var == "target_base_position"
            ]
            goto.append(
                {
                    "to": values,
                    "calls": leaf_calls(branch, uid_to_name),
                    "tags": [c.tag for c in branch if c.tag not in NOISE],
                    "body": branch,
                }
            )
    return {"leave": leave, "goto": goto}


def base_routes(root: ET.Element, uid_to_name, by_name) -> dict[str, list[dict]]:
    """base_branches without the elements, so the result can be serialised."""
    found = base_branches(uid_to_name, by_name)
    return {
        kind: [{k: v for k, v in entry.items() if k != "body"} for entry in entries]
        for kind, entries in found.items()
    }


def main() -> int:
    root, uid_to_name, by_name = load()
    result = {
        "pick": arm_routes("PickHandler", root, uid_to_name, by_name),
        "place": arm_routes("PlaceHandler", root, uid_to_name, by_name),
        "base": base_routes(root, uid_to_name, by_name),
    }

    for kind in ("pick", "place"):
        print(f"=== {kind} ({len(result[kind])} branches) ===")
        for entry in result[kind]:
            calls = entry["calls"]
            marker = "" if len(calls) == 1 else f"   <-- {len(calls)} calls"
            print(f"  {entry['region']:<22} {str(entry['slot']):<26} {calls}{marker}")
        print()

    print("=== base: leave ===")
    for entry in result["base"]["leave"]:
        print(f"  from={entry['from']} calls={entry['calls']} tags={entry['tags']}")
    print("\n=== base: goto ===")
    for entry in result["base"]["goto"]:
        print(f"  to={entry['to']} calls={entry['calls']} tags={entry['tags']}")

    out = Path(__file__).with_name("routes_from_xml.json")
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
