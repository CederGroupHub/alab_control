"""Inventory the exported Main archive: functions, call edges, and variable scopes.

Read-only probe. Answers two questions the split depends on:
  1. which function owns the single <Global>0</Global> variable access
  2. the full function list plus call graph, so functions can be assigned to libraries
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)

# Every call element that names a target function block.
CALL_TAGS = ("CallFunctionBlock", "CallIncProgFunction")


def load() -> ET.Element:
    return ET.parse(MAIN).getroot()


def parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def enclosing_function(
    node: ET.Element, parent_of: dict[ET.Element, ET.Element]
) -> str:
    """Walk up to the FunctionBlock or Program that contains this node."""
    cursor = node
    while cursor is not None:
        if cursor.tag in ("FunctionBlock", "Program"):
            return (cursor.findtext("Name") or "?").strip()
        cursor = parent_of.get(cursor)
    return "<archive top level>"


def main() -> int:
    root = load()
    parent_of = parents(root)

    functions: dict[str, ET.Element] = {}
    name_of_uid: dict[str, str] = {}
    for block in root.iter("FunctionBlock"):
        name = (block.findtext("Name") or "").strip()
        uid = (block.findtext("UID") or "").strip()
        if not name:
            continue
        functions[name] = block
        if uid:
            name_of_uid[uid] = name

    programs = [
        {
            "name": (p.findtext("Name") or "").strip(),
            "uid": (p.findtext("UID") or "").strip(),
            "includes": (p.findtext("IncludeProgramFuncs") or "").strip(),
            "instruction_tags": [child.tag for child in (p.find("Instructions") or [])],
        }
        for p in root.iter("Program")
    ]

    # Call edges, by owning function.
    edges: dict[str, list[str]] = {}
    unresolved: list[tuple[str, str]] = []
    for tag in CALL_TAGS:
        for call in root.iter(tag):
            target_uid = (call.findtext("FunctionBlockName") or "").strip()
            owner = enclosing_function(call, parent_of)
            callee = name_of_uid.get(target_uid)
            if callee is None:
                if target_uid:
                    unresolved.append((owner, target_uid))
                continue
            edges.setdefault(owner, [])
            if callee not in edges[owner]:
                edges[owner].append(callee)

    # Variable scope flags.
    scope_hits: list[dict[str, str]] = []
    for tag in ("SaveVariable", "LoadVariable"):
        for node in root.iter(tag):
            flag = (node.findtext("Global") or "").strip()
            var = node.findtext("Variable/Name")
            if var is None:
                var = node.findtext("LHS/Variable/Name")
            scope_hits.append(
                {
                    "tag": tag,
                    "variable": (var or "?").strip(),
                    "global": flag,
                    "function": enclosing_function(node, parent_of),
                }
            )

    print(f"functions: {len(functions)}")
    print(f"programs: {[p['name'] for p in programs]}")
    for p in programs:
        print(f"  program {p['name']!r} uid={p['uid']!r} includes={p['includes']!r}")
        print(f"    entry instructions: {p['instruction_tags']}")

    print(f"\nvariable accesses: {len(scope_hits)}")
    print(f"  by Global flag: {dict(Counter(h['global'] for h in scope_hits))}")
    print("  non-global accesses:")
    for hit in scope_hits:
        if hit["global"] != "1":
            print(
                f"    {hit['tag']} {hit['variable']!r} Global={hit['global']!r} "
                f"in function {hit['function']!r}"
            )

    if unresolved:
        print(f"\nunresolved call targets: {len(unresolved)}")
        for owner, uid in unresolved[:20]:
            print(f"    {owner!r} -> {uid!r}")

    # Reachability from the program entry.
    entry_targets: list[str] = []
    for p in root.iter("Program"):
        for tag in CALL_TAGS:
            for call in p.iter(tag):
                callee = name_of_uid.get((call.findtext("FunctionBlockName") or "").strip())
                if callee:
                    entry_targets.append(callee)

    seen: set[str] = set()
    stack = list(entry_targets)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edges.get(current, []))

    orphans = sorted(set(functions) - seen)
    print(f"\nreachable from entry: {len(seen)}")
    print(f"orphaned: {len(orphans)}")
    for name in orphans:
        print(f"    {name}")

    out = Path(__file__).with_name("inventory.json")
    out.write_text(
        json.dumps(
            {
                "functions": sorted(functions),
                "uid_to_name": name_of_uid,
                "edges": edges,
                "entry_targets": entry_targets,
                "reachable": sorted(seen),
                "orphans": orphans,
                "programs": programs,
                "non_global_accesses": [h for h in scope_hits if h["global"] != "1"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
