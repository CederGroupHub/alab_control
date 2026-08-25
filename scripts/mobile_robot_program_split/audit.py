"""Check the generated archives hang together before anything is uploaded.

The controller will not tell us politely that a call points at nothing; it will either
refuse the program or run the wrong motion. So verify here that every call resolves,
that cross-program calls name a program that really holds the function, and that no
reference to the old Main namespace survived.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from assignment import LIBRARIES  # noqa: E402

from alab_control.mobile_robot_arm import programs as P  # noqa: E402

OUT = HERE / "split_programs"
CALL_TAGS = ("CallFunctionBlock", "CallIncProgFunction")
PROGRAM_FIELDS = ("Name", "Description", "UID", "Instructions", "IncludeProgramFuncs")
B = "{https://developers.google.com/blockly/xml}"
FRONT_CALL_TYPES = ("er_call_function_block", "er_call_prog_function_2")
#: Written by nothing in Blockly because the controller fills it in when the program is
#: loaded: the named arguments arrive as this dictionary.
LOADER_SUPPLIED = ("arguments",)


def fields_of(block: ET.Element) -> dict[str, str]:
    return {f.get("name"): (f.text or "") for f in block.findall(f"{B}field")}


def front_chain(statement: ET.Element | None) -> list[ET.Element]:
    if statement is None:
        return []
    out: list[ET.Element] = []
    cursor = statement.find(f"{B}block")
    while cursor is not None:
        out.append(cursor)
        nxt = cursor.find(f"{B}next")
        cursor = nxt.find(f"{B}block") if nxt is not None else None
    return out


def check_frontend(name: str, program_root: ET.Element, folder: Path) -> list[str]:
    """The canvas must describe the same program the controller will execute."""
    found: list[str] = []
    path = folder / "frontend.xml"
    if not path.is_file():
        return [f"{name}: frontend.xml missing"]
    try:
        canvas = ET.parse(path).getroot()
    except ET.ParseError as error:
        return [f"{name}: frontend.xml will not parse: {error}"]

    program = program_root.find("Program")
    definitions = {
        block.get("id"): block
        for block in canvas.findall(f"{B}block")
        if block.get("type") == "er_function_block"
    }
    er_programs = [
        block for block in canvas.findall(f"{B}block") if block.get("type") == "er_program"
    ]
    if len(er_programs) != 1:
        found.append(f"{name}: expected one er_program block, found {len(er_programs)}")
    else:
        block = er_programs[0]
        if block.get("id") != (program.findtext("UID") or "").strip():
            found.append(f"{name}: er_program id does not match the Program UID")
        progname = fields_of(block).get("_progName", "")
        if progname != (program.findtext("IncludeProgramFuncs") or "").strip():
            found.append(f"{name}: _progName does not match IncludeProgramFuncs")

    # One canvas definition per executable function, and the same instruction count.
    blocks = {
        (b.findtext("UID") or "").strip(): b for b in program_root.iter("FunctionBlock")
    }
    # A canvas id is the executable UID without its owning program prefix. Program
    # names contain underscores, so strip the known prefix rather than splitting.
    bare = {
        (uid[len(name) + 1 :] if uid.startswith(name + "_") else uid): uid
        for uid in blocks
    }
    if set(definitions) != set(bare):
        found.append(
            f"{name}: canvas definitions {sorted(set(definitions) - set(bare))} / "
            f"missing {sorted(set(bare) - set(definitions))}"
        )
    for block_id, definition in definitions.items():
        uid = bare.get(block_id)
        if uid is None:
            continue
        executable = blocks[uid].find("Body/Sequence/Instructions")
        expected = len(list(executable)) if executable is not None else 0
        actual = len(front_chain(definition.find(f"{B}statement")))
        if expected != actual:
            found.append(
                f"{name}: {block_id} has {expected} instructions but "
                f"{actual} canvas blocks"
            )

    for call in canvas.iter(f"{B}block"):
        if call.get("type") not in FRONT_CALL_TYPES:
            continue
        values = fields_of(call)
        if call.get("type") == "er_call_prog_function_2":
            owner = values.get("programName", "")
            target = values.get("functionUiD", "")
            if not target.startswith(owner + "_"):
                found.append(f"{name}: canvas call {target!r} not owned by {owner!r}")
            if values.get("programNameDrop") != owner or values.get("functionUiDDrop") != target:
                found.append(f"{name}: canvas call drop fields disagree with the real ones")
        else:
            target = values.get("FunctionBlockName", "")
            if target not in definitions:
                found.append(
                    f"{name}: canvas local call to {target!r} has no definition here"
                )
    return found


def main() -> int:
    problems: list[str] = []
    archives: dict[str, ET.Element] = {}
    local_uids: dict[str, set[str]] = {}

    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir():
            continue
        path = folder / "program.xml"
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as error:
            problems.append(f"{folder.name}: will not parse: {error}")
            continue
        archives[folder.name] = root
        local_uids[folder.name] = {
            (b.findtext("UID") or "").strip() for b in root.iter("FunctionBlock")
        }
        problems.extend(check_frontend(folder.name, root, folder))

    print(f"archives parsed: {len(archives)}")
    if not (OUT / "data.xml").is_file():
        problems.append("the shared data.xml is missing")
    expected = set(LIBRARIES) | set(P.ENTRY_PROGRAMS)
    if set(archives) != expected:
        problems.append(
            f"archive set differs from the table: "
            f"missing {sorted(expected - set(archives))}, "
            f"unexpected {sorted(set(archives) - expected)}"
        )

    library_uids = {lib: local_uids.get(lib, set()) for lib in LIBRARIES}
    total_functions = sum(len(library_uids[lib]) for lib in LIBRARIES)
    print(f"library functions: {total_functions}")

    stale = 0
    cross_calls = 0
    local_calls = 0

    for name, root in archives.items():
        program = root.find("Program")
        if program is None:
            problems.append(f"{name}: no Program element")
            continue
        for field in PROGRAM_FIELDS:
            if program.find(field) is None:
                problems.append(f"{name}: Program is missing <{field}>")
        if (program.findtext("Name") or "").strip() != name:
            problems.append(f"{name}: Program Name does not match the folder")

        includes = [
            part
            for part in (program.findtext("IncludeProgramFuncs") or "").split(";")
            if part
        ]
        for include in includes:
            if include not in LIBRARIES:
                problems.append(f"{name}: includes unknown program {include!r}")
        if name in includes:
            problems.append(f"{name}: includes itself")

        # A library is never started directly, so it has no entry instructions. An
        # entry program must have exactly one, calling its own Entry function.
        instructions = list(program.find("Instructions") or [])
        if name in LIBRARIES:
            if instructions:
                problems.append(f"{name}: a library should have no entry instructions")
        else:
            if len(instructions) != 1:
                problems.append(
                    f"{name}: expected one entry instruction, found {len(instructions)}"
                )
            elif instructions[0].tag != "CallFunctionBlock":
                problems.append(
                    f"{name}: entry instruction is {instructions[0].tag}, "
                    "expected CallFunctionBlock"
                )
            else:
                target = (instructions[0].findtext("FunctionBlockName") or "").strip()
                if target not in local_uids[name]:
                    problems.append(f"{name}: entry call does not target a local block")

        for text in root.itertext():
            if "Main_test_" in text:
                stale += 1
                problems.append(f"{name}: still references the Main namespace")
                break

        for call in [c for tag in CALL_TAGS for c in root.iter(tag)]:
            target = (call.findtext("FunctionBlockName") or "").strip()
            if call.tag == "CallFunctionBlock":
                local_calls += 1
                if call.find("ProgramName") is not None:
                    problems.append(f"{name}: local call carries a ProgramName")
                if target not in local_uids[name]:
                    problems.append(
                        f"{name}: local call to {target!r} has no matching block here"
                    )
                continue

            cross_calls += 1
            owner = (call.findtext("ProgramName") or "").strip()
            if not owner:
                problems.append(f"{name}: cross-program call without a ProgramName")
                continue
            if owner not in LIBRARIES:
                problems.append(f"{name}: cross-program call into {owner!r}")
                continue
            if owner not in includes:
                problems.append(f"{name}: calls {owner!r} but does not include it")
            if not target.startswith(owner + "_"):
                problems.append(
                    f"{name}: call target {target!r} is not prefixed with {owner!r}"
                )
            if target not in library_uids[owner]:
                problems.append(f"{name}: {owner} does not contain {target!r}")

    print(f"calls: {local_calls} local, {cross_calls} cross-program")
    print(f"archives still naming Main: {stale}")

    # Every library function should be reachable from some entry program, otherwise it
    # is dead on the controller. Tests is exempt, that is what it is for.
    reachable: set[str] = set()
    frontier = [name for name in archives if name not in LIBRARIES]
    seen_programs: set[str] = set()
    while frontier:
        current = frontier.pop()
        if current in seen_programs:
            continue
        seen_programs.add(current)
        root = archives.get(current)
        if root is None:
            continue
        for call in root.iter("CallIncProgFunction"):
            owner = (call.findtext("ProgramName") or "").strip()
            target = (call.findtext("FunctionBlockName") or "").strip()
            if target and target not in reachable:
                reachable.add(target)
                frontier.append(owner)
        for call in root.iter("CallFunctionBlock"):
            target = (call.findtext("FunctionBlockName") or "").strip()
            if current in LIBRARIES and target:
                reachable.add(target)

    unreachable = {
        lib: sorted(library_uids[lib] - reachable)
        for lib in LIBRARIES
        if lib != "Tests"
    }
    dead = {lib: uids for lib, uids in unreachable.items() if uids}
    print("\nlibrary blocks never called from an entry program:")
    if not dead:
        print("  none")
    for lib, uids in dead.items():
        print(f"  {lib}: {len(uids)}")
        for uid in uids:
            print(f"      {uid}")

    # A scratch variable has to be written and read inside one program. It never touches
    # the controller's global store, so a value set in an entry program is simply not
    # there when a library function looks for it. This is the check that caught the
    # crucible routes, where the rack origin was chosen in a dispatcher that became an
    # entry program while the function reading it stayed in a library.
    persisted = {
        (node.findtext("Variable/Name") or node.findtext("LHS/Variable/Name") or "").strip()
        for root in archives.values()
        for node in root.iter("SaveVariable")
    }
    starved = 0
    for name, root in sorted(archives.items()):
        parent_of = {child: parent for parent in root.iter() for child in parent}
        reads: set[str] = set()
        writes: set[str] = set()
        for var in root.iter("Variable"):
            variable = (var.findtext("Name") or "").strip()
            if not variable or variable in persisted:
                continue
            cursor, reading = parent_of.get(var), False
            while cursor is not None and cursor.tag not in ("FunctionBlock", "Program"):
                if cursor.tag in ("RHS", "Condition"):
                    reading = True
                    break
                cursor = parent_of.get(cursor)
            (reads if reading else writes).add(variable)
        for variable in sorted(reads - writes):
            if variable in LOADER_SUPPLIED and name not in LIBRARIES:
                # An entry program is the one that gets loaded, so its arguments are
                # handed to it from outside. A library is never loaded, so the same read
                # there would find nothing.
                continue
            starved += 1
            problems.append(
                f"{name}: reads the scratch variable {variable!r}, which nothing in "
                f"the same program writes"
            )
    print(f"\nscratch variables read without a writer in the same program: {starved}")

    print(f"\n{'PROBLEMS: ' + str(len(problems)) if problems else 'audit clean'}")
    for problem in problems[:40]:
        print(f"  - {problem}")
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
