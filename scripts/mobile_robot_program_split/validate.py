"""Check the library assignment before generating anything.

Two checks and one report:
  1. every function in the archive is assigned somewhere
  2. which call edges become cross-program (those need CallIncProgFunction + an include)
  3. which libraries read a scratch variable nothing in that library writes

The third is a report rather than a failure, because from here it cannot be answered.
A variable saved with ``SaveVariable Global=1`` travels through the controller's global
store, so it survives a program boundary and can be read anywhere. A pure scratch
variable never touches the store, so its writer has to run in the same program as its
reader -- and whether it does depends on where the generator puts the dispatcher code it
lifts, which has not happened yet. ``audit.py`` asks the same question of the generated
archives, where it has a real answer.

It is still worth reading when editing the assignment map, because it says which
libraries depend on a write they do not contain. ``x_dim`` does not appear: it is touched
in three libraries and safe in all of them, because ``ALSO_IN`` duplicates the function
that computes it into each.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from assignment import ALSO_IN, ASSIGNMENT, DROP, LIBRARIES  # noqa: E402
from routes_from_xml import MAIN  # noqa: E402

CALL_TAGS = ("CallFunctionBlock", "CallIncProgFunction")
#: A variable reference is a read when it sits inside an expression or a test, and a
#: write otherwise. That covers all the forms Main uses without enumerating instruction
#: types: `Assign/LHS`, `LoadVariable/LHS`, and an instruction's own output slot such as
#: `URAction/Response` or `IsWaypointReachable` are writes, while anything under `RHS`
#: or `Condition` is a read.
READING_CONTEXT = ("RHS", "Condition")


def main() -> int:
    root = ET.parse(MAIN).getroot()
    parent_of = {child: parent for parent in root.iter() for child in parent}

    def owner(node: ET.Element) -> str:
        cursor = node
        while cursor is not None:
            if cursor.tag in ("FunctionBlock", "Program"):
                return (cursor.findtext("Name") or "?").strip()
            cursor = parent_of.get(cursor)
        return "<top level>"

    functions = {
        (b.findtext("Name") or "").strip(): b
        for b in root.iter("FunctionBlock")
        if (b.findtext("Name") or "").strip()
    }
    name_of_uid = {
        (b.findtext("UID") or "").strip(): (b.findtext("Name") or "").strip()
        for b in root.iter("FunctionBlock")
    }

    problems = 0

    # 1. Coverage.
    missing = sorted(set(functions) - set(ASSIGNMENT))
    extra = sorted(set(ASSIGNMENT) - set(functions))
    print(f"functions in archive: {len(functions)}, assigned: {len(ASSIGNMENT)}")
    if missing:
        problems += 1
        print(f"  UNASSIGNED ({len(missing)}):")
        for name in missing:
            print(f"    {name}")
    if extra:
        problems += 1
        print(f"  assigned but not in archive ({len(extra)}):")
        for name in extra:
            print(f"    {name}")
    if not missing and not extra:
        print("  coverage OK")

    counts = defaultdict(int)
    for name, lib in ASSIGNMENT.items():
        counts[lib] += 1
    print("\nfunctions per library:")
    for lib in (*LIBRARIES, DROP):
        print(f"  {lib:<16} {counts[lib]}")

    # 2. Cross-program call edges.
    cross: dict[str, set[str]] = defaultdict(set)
    dropped_callers: list[tuple[str, str]] = []
    for tag in CALL_TAGS:
        for call in root.iter(tag):
            callee = name_of_uid.get((call.findtext("FunctionBlockName") or "").strip())
            if not callee:
                continue
            caller = owner(call)
            caller_lib = ASSIGNMENT.get(caller)
            callee_lib = ASSIGNMENT.get(callee)
            if caller_lib == DROP:
                dropped_callers.append((caller, callee))
                continue
            if caller_lib and callee_lib and caller_lib != callee_lib:
                if callee_lib == DROP:
                    problems += 1
                    print(f"  ERROR: {caller!r} calls dropped function {callee!r}")
                    continue
                cross[caller_lib].add(callee_lib)

    print("\nincludes each library needs:")
    for lib in LIBRARIES:
        needed = sorted(cross.get(lib, ()))
        print(f"  {lib:<16} {';'.join(needed) if needed else '(none)'}")

    print(f"\ncalls made by dropped dispatchers (become entry programs): {len(dropped_callers)}")

    # 3. Scratch variables read where nothing writes them.
    persisted: set[str] = set()
    for node in root.iter("SaveVariable"):
        name = node.findtext("Variable/Name") or node.findtext("LHS/Variable/Name")
        if name:
            persisted.add(name.strip())

    def is_read(node: ET.Element) -> bool:
        cursor = parent_of.get(node)
        while cursor is not None and cursor.tag not in ("FunctionBlock", "Program"):
            if cursor.tag in READING_CONTEXT:
                return True
            cursor = parent_of.get(cursor)
        return False

    written: dict[str, set[str]] = defaultdict(set)
    read: dict[str, set[str]] = defaultdict(set)
    for var in root.iter("Variable"):
        name = (var.findtext("Name") or "").strip()
        if not name:
            continue
        side = read if is_read(var) else written
        side[name].add(owner(var))

    def callees(name: str) -> list[str]:
        found = []
        for tag in CALL_TAGS:
            for call in functions[name].iter(tag):
                callee = name_of_uid.get(
                    (call.findtext("FunctionBlockName") or "").strip()
                )
                if callee and callee != name:
                    found.append(callee)
        return found

    def closure(name: str) -> set[str]:
        seen: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen or current not in functions:
                continue
            seen.add(current)
            stack.extend(callees(current))
        return seen

    # Effective membership, the way the generator computes it: a function duplicated by
    # ALSO_IN, and everything it calls, belongs to several libraries at once.
    members: dict[str, set[str]] = {
        lib: {fn for fn, owner_lib in ASSIGNMENT.items() if owner_lib == lib}
        for lib in LIBRARIES
    }
    for name, extras in ALSO_IN.items():
        for lib in extras:
            members[lib] |= closure(name)

    scratch = {v for v in read if v not in persisted}
    unfed: list[tuple[str, str, list[str]]] = []
    for var in sorted(scratch):
        for lib in LIBRARIES:
            readers = read[var] & members[lib]
            if readers and not (written[var] & members[lib]):
                unfed.append((var, lib, sorted(readers)))

    print(f"\nvariables persisted via SaveVariable: {len(persisted)}")
    print(f"scratch variables (never persisted): {len(scratch)}")
    print("  persisted ones are safe anywhere: they travel through the global store")

    print(f"\nscratch variables read by a library that does not write them: {len(unfed)}")
    if unfed:
        print("  the write has to come from lifted dispatcher code; audit.py checks it")
        for var, lib, readers in unfed:
            print(f"    {var:<26} {lib}")
            for fn in readers:
                print(f"        reads in {fn}")

    print(f"\n{'PROBLEMS FOUND' if problems else 'all checks passed'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
