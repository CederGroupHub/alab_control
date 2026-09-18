"""Split Main into nine function libraries plus one thin entry program per route.

Nothing here authors Blockly by hand. Every instruction in the output is lifted out of
Main, and the executable ``program.xml`` and the editable ``frontend.xml`` are built in
lockstep from the same walk, because the two files must agree instruction for
instruction or the IDE shows something different from what the arm does.

The dispatch that used to live in ``BaseHandler`` / ``PickHandler`` / ``PlaceHandler``
moves to alab_control.mobile_robot_arm.programs. What is left of each handler, the
calibration call, the TryCatch and its recovery body, and the grip check, is lifted
into Shared helpers so an entry program is a short readable chain of calls.

Run:  python scripts/mobile_robot_program_split/generator.py
Out:  scripts/mobile_robot_program_split/split_programs/<Program>/{program.xml,frontend.xml}
      plus one shared data.xml beside them
"""

from __future__ import annotations

import copy
import hashlib
import shutil
import string
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from assignment import ALSO_IN, ASSIGNMENT, DROP, LIBRARIES, SHARED  # noqa: E402
from routes_from_xml import (  # noqa: E402
    MAIN_DIR,
    arm_branches,
    compare_parts,
    composite_values,
    load,
    steps,
)

from alab_control.mobile_robot_arm import programs as P  # noqa: E402

OUT = HERE / "split_programs"
PREFIX = "Main_test_"
B = "{https://developers.google.com/blockly/xml}"
UID_ALPHABET = string.ascii_letters + string.digits
CALL_TAGS = ("CallFunctionBlock", "CallIncProgFunction")

#: Helpers lifted out of Main_program and the two pick/place handlers so that the entry
#: programs stay short. Names are ours; every instruction inside is Main's.
PICK_PROLOGUE = "PickPrologue"
PLACE_PROLOGUE = "PlacePrologue"
PICK_POSTCHECK = "PickPostcheck"

#: The four crucible branches of each arm ladder pick the same leaf function but load a
#: different rack origin into ``GridOrigin`` first, so they are one movement parametrised
#: by a calibration pose rather than four movements. The selection has to live in the
#: same program as the leaf, because ``GridOrigin`` is scratch and would not survive the
#: hop from an entry program into the library. So it is lifted into ``On_Robot``, whole,
#: and the entry program calls that instead of the leaf directly.
ON_ROBOT = "On_Robot"
CRUCIBLE_PICK = "PickCrucibleFromRobotBase"
CRUCIBLE_PLACE = "PlaceCrucibleOnRobotBase"
CRUCIBLE_REGIONS = (
    "ROBOT_BASE/SubRackA",
    "ROBOT_BASE/SubRackB",
    "ROBOT_BASE/SubRackC",
    "ROBOT_BASE/SubRackD",
)

#: Every function this generator synthesises, and which library it belongs to. Ordered,
#: so the emitted archives are stable.
SYNTHESISED = {
    PICK_PROLOGUE: SHARED,
    PLACE_PROLOGUE: SHARED,
    PICK_POSTCHECK: SHARED,
    CRUCIBLE_PICK: ON_ROBOT,
    CRUCIBLE_PLACE: ON_ROBOT,
}

#: Main's own "the base is not where I think it is" check, used as the guard template.
#: ``Out from IXRD`` opens with it, so the shape is Main's rather than ours.
GUARD_SOURCE = ("Out from IXRD", "IXRD")

#: Entry programs that assert the base is at Home before they drive. Every goto but
#: ``Run_GoTo_Home``, which the table also uses to leave a pose no ``Run_OutFrom_*``
#: covers, exactly as BaseHandler drove Home when BasePosition matched no leave branch.
GUARDED = frozenset(
    program for target, program in P.GOTO.items() if target != P.HOME
)


def uid_from(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).digest()
    return "".join(UID_ALPHABET[b % len(UID_ALPHABET)] for b in digest[:20])


def fields_of(block: ET.Element) -> dict[str, str]:
    return {f.get("name"): (f.text or "") for f in block.findall(f"{B}field")}


def set_field(block: ET.Element, name: str, value: str) -> None:
    for field in block.findall(f"{B}field"):
        if field.get("name") == name:
            field.text = value
            return
    field = ET.SubElement(block, f"{B}field")
    field.set("name", name)
    field.text = value


def front_chain(statement: ET.Element | None) -> list[ET.Element]:
    """The blocks of a Blockly statement, following the <next> links."""
    if statement is None:
        return []
    out: list[ET.Element] = []
    cursor = statement.find(f"{B}block")
    while cursor is not None:
        out.append(cursor)
        nxt = cursor.find(f"{B}next")
        cursor = nxt.find(f"{B}block") if nxt is not None else None
    return out


def detach(block: ET.Element) -> ET.Element:
    """A copy of a block with its trailing chain removed."""
    clone = copy.deepcopy(block)
    for nxt in clone.findall(f"{B}next"):
        clone.remove(nxt)
    return clone


def set_front_chain(statement: ET.Element, blocks: list[ET.Element]) -> None:
    """Replace a statement's contents with ``blocks``, relinking them in order."""
    for child in list(statement):
        statement.remove(child)
    if not blocks:
        return
    detached = [detach(block) for block in blocks]
    statement.append(detached[0])
    cursor = detached[0]
    for block in detached[1:]:
        nxt = ET.SubElement(cursor, f"{B}next")
        nxt.append(block)
        cursor = block


class Splitter:
    def __init__(self) -> None:
        self.root, self.uid_to_name, self.by_name = load()
        self.name_to_uid = {name: uid for uid, name in self.uid_to_name.items()}
        for name, uid in self.name_to_uid.items():
            if not uid.startswith(PREFIX):
                raise AssertionError(f"{name!r} has unexpected UID {uid!r}")

        self.front = ET.parse(MAIN_DIR / "frontend.xml").getroot()
        self.definitions = {
            fields_of(block).get("FunctionBlockName", ""): block
            for block in self.front.findall(f"{B}block")
            if block.get("type") == "er_function_block"
        }
        self.metadata = self.front.find("metadata")
        self.version = self.front.find("version")
        self.variables = self.front.find(f"{B}variables")

        self.members = self._members()
        self.lifted: dict[str, tuple[ET.Element, ET.Element]] = {}
        self.guard_template: tuple[ET.Element, ET.Element] | None = None
        self.notes: list[str] = []
        self.uid_counter = 0

    # ---------------------------------------------------------------- assignment

    def callees(self, name: str) -> list[str]:
        found = []
        for tag in CALL_TAGS:
            for call in self.by_name[name].iter(tag):
                callee = self.uid_to_name.get(
                    (call.findtext("FunctionBlockName") or "").strip()
                )
                if callee and callee != name:
                    found.append(callee)
        return found

    def closure(self, name: str) -> set[str]:
        seen: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.callees(current))
        return seen

    def _members(self) -> dict[str, set[str]]:
        members: dict[str, set[str]] = {lib: set() for lib in LIBRARIES}
        for name, lib in ASSIGNMENT.items():
            if lib != DROP:
                members[lib].add(name)
        for name, extras in ALSO_IN.items():
            for lib in extras:
                members[lib] |= self.closure(name)
        return members

    def home_of(self, name: str, viewed_from: str) -> str:
        if name in SYNTHESISED:
            return SYNTHESISED[name]
        if name in self.members.get(viewed_from, ()):
            return viewed_from
        return ASSIGNMENT[name]

    def full_uid(self, name: str, lib: str) -> str:
        if name in SYNTHESISED:
            return f"{lib}_{uid_from('lifted:' + name)}"
        return lib + "_" + self.name_to_uid[name][len(PREFIX) :]

    def bare_uid(self, name: str, lib: str) -> str:
        """The canvas form of a UID: the same id without the owning program prefix."""
        return self.full_uid(name, lib)[len(lib) + 1 :]

    def next_uid(self, seed: str) -> str:
        self.uid_counter += 1
        return uid_from(f"{seed}:{self.uid_counter}")

    # -------------------------------------------------------------------- paired

    def paired(self, name: str) -> list[tuple[ET.Element, ET.Element]]:
        """A function's instructions, program.xml element beside canvas block."""
        instructions = self.by_name[name].find("Body/Sequence/Instructions")
        canvas = front_chain(self.definitions[name].find(f"{B}statement"))
        nodes = list(instructions)
        if len(nodes) != len(canvas):
            raise AssertionError(
                f"{name}: program.xml has {len(nodes)} instructions but the canvas has "
                f"{len(canvas)}; positional pairing would misalign"
            )
        return list(zip(nodes, canvas))

    def paired_body(
        self, xml_node: ET.Element, front_block: ET.Element, xml_slot: str, front_slot: str
    ) -> list[tuple[ET.Element, ET.Element]]:
        nodes = steps(xml_node.find(xml_slot))
        canvas = front_chain(
            front_block.find(f'{B}statement[@name="{front_slot}"]')
        )
        if len(nodes) != len(canvas):
            raise AssertionError(
                f"{xml_slot}/{front_slot}: {len(nodes)} vs {len(canvas)} instructions"
            )
        return list(zip(nodes, canvas))

    def paired_ladder(self, xml_if: ET.Element, front_if: ET.Element):
        """Walk a dispatch ladder in both files at once.

        The two encode the same ladder differently: program.xml nests each else-if
        inside the previous ElseBody, while the canvas keeps one block with flat
        IF0/DO0 .. IFn/DOn slots. So nesting depth on one side is the slot index on
        the other. Yields (xml If node, canvas block, canvas slot name).
        """
        xml_current: ET.Element | None = xml_if
        index = 0
        while xml_current is not None:
            yield xml_current, front_if, f"DO{index}"
            else_body = xml_current.find("ElseBody")
            nested = (
                [c for c in steps(else_body) if c.tag == "If"]
                if else_body is not None
                else []
            )
            if not nested:
                return
            xml_current = nested[0]
            index += 1

    # ------------------------------------------------------------------- calls

    def make_call(
        self, function: str, from_program: str, seed: str
    ) -> tuple[ET.Element, ET.Element]:
        """A matched pair of call elements, local or cross-program as appropriate."""
        target = self.home_of(function, from_program)
        full = self.full_uid(function, target)
        bare = full[len(target) + 1 :]
        uid = self.next_uid(seed)
        cross = target != from_program

        if cross:
            xml = ET.Element("CallIncProgFunction")
            spec = (
                ("Name", "CallIncProgFunction"),
                ("Version", "0.1.0"),
                ("UID", uid),
                ("IsInitialized", "1"),
                ("IsErrorFunctionActive", "0"),
                ("ErrorFunctionName", ""),
                ("ErrorFunctionUid", ""),
                ("RetryAttempts", "0"),
                ("FunctionBlockName", full),
                ("ProgramName", target),
            )
            front = ET.Element(f"{B}block")
            front.set("type", "er_call_prog_function_2")
            front.set("id", uid)
            front_fields = (
                ("programNameDrop", target),
                ("functionUiDDrop", full),
                ("programName", target),
                ("functionUiD", full),
                ("IsSafe", "1"),
                ("IsActive", "0"),
                ("Attempts", "0"),
                ("ErrorFunctionName", ""),
                ("ErrorFunctionUid", ""),
            )
        else:
            xml = ET.Element("CallFunctionBlock")
            spec = (
                ("Name", "CallFunctionBlock"),
                ("UID", uid),
                ("Version", "0.1.0"),
                ("IsInitialized", "1"),
                ("FunctionBlockName", full),
            )
            front = ET.Element(f"{B}block")
            front.set("type", "er_call_function_block")
            front.set("id", uid)
            front_fields = (
                ("FunctionBlockNameDrop", bare),
                ("FunctionBlockName", bare),
                ("IsSafe", "1"),
                ("IsActive", "0"),
                ("Attempts", "0"),
                ("ErrorFunctionName", ""),
                ("ErrorFunctionUid", ""),
            )

        for tag, text in spec:
            ET.SubElement(xml, tag).text = text
        for tag, text in front_fields:
            field = ET.SubElement(front, f"{B}field")
            field.set("name", tag)
            field.text = text
        return xml, front

    def retype_calls(self, xml_block: ET.Element, front_block: ET.Element, lib: str) -> None:
        """Point every call in a copied function at its function's new home."""
        pending = [
            (parent, index, child)
            for parent in xml_block.iter()
            for index, child in enumerate(parent)
            if child.tag in CALL_TAGS
        ]
        for parent, index, child in pending:
            name = self.uid_to_name.get(
                (child.findtext("FunctionBlockName") or "").strip()
            )
            if name is None:
                continue
            uid = (child.findtext("UID") or "").strip()
            replacement, _ = self.make_call(name, lib, uid)
            replacement.find("UID").text = uid
            parent[index] = replacement

        front_pending = [
            (parent, index, child)
            for parent in front_block.iter()
            for index, child in enumerate(parent)
            if child.tag == f"{B}block"
            and child.get("type") in ("er_call_function_block", "er_call_prog_function_2")
        ]
        for parent, index, child in front_pending:
            values = fields_of(child)
            bare = values.get("FunctionBlockName") or values.get("functionUiD", "")
            name = self.uid_to_name.get(PREFIX + bare)
            if name is None:
                continue
            _, replacement = self.make_call(name, lib, child.get("id") or bare)
            replacement.set("id", child.get("id") or replacement.get("id"))
            # Move the trailing chain rather than copying it. Blockly links siblings
            # through <next>, so copying would orphan the blocks further down the chain
            # and any replacement still queued for them would land on a discarded copy.
            for nxt in list(child.findall(f"{B}next")):
                child.remove(nxt)
                replacement.append(nxt)
            parent[index] = replacement

    # ------------------------------------------------------------------- lifting

    def build_lifted(self) -> None:
        """Create the Shared helpers out of Main_program and the handler wrappers."""
        main_pairs = self.paired("Main_program")
        cut = 0
        for index, (node, _) in enumerate(main_pairs):
            if node.tag == "If":
                parts = compare_parts(node.find("Condition"))
                if parts is None or parts[0] not in ("source_slot", "destination_slot"):
                    cut = index
                    break
        # Where Main starts turning the slot strings into integers. Everything before it
        # reads the `arguments` dictionary and saves what it finds, so it is inlined into
        # every entry program: the controller hands the arguments to whichever program it
        # loads, and that is the entry program, not a library. Everything this produces
        # goes through SaveVariable, so the libraries downstream read it out of the global
        # store rather than depending on it having run next door.
        slot_at = next(
            index
            for index, (node, _) in enumerate(main_pairs)
            if node.tag == "If"
            and (compare_parts(node.find("Condition")) or (None,))[0]
            in ("source_slot", "destination_slot")
        )
        self.preamble = main_pairs[:slot_at]
        if not self.preamble:
            raise AssertionError("the entry preamble came out empty")

        # The integer slots are not saved anywhere, so each conversion has to travel with
        # the prologue that reads it rather than staying behind in the entry program.
        slot_guard: dict[str, tuple[ET.Element, ET.Element]] = {}
        for node, front in main_pairs[slot_at:cut]:
            parts = compare_parts(node.find("Condition")) if node.tag == "If" else None
            if parts and parts[0] in ("source_slot", "destination_slot"):
                slot_guard[parts[0]] = (node, front)
        missing = {"source_slot", "destination_slot"} - set(slot_guard)
        if missing:
            raise AssertionError(f"no slot conversion found for {sorted(missing)}")

        region_if = next(
            (node, front)
            for node, front in reversed(main_pairs)
            if node.tag == "If" and compare_parts(node.find("Condition")) is None
        )
        body = self.paired_body(region_if[0], region_if[1], "IfBody", "DO0")

        def call_index(handler: str) -> int:
            wanted = self.name_to_uid[handler]
            for index, (node, _) in enumerate(body):
                if node.tag in CALL_TAGS and (
                    node.findtext("FunctionBlockName") or ""
                ).strip() == wanted:
                    return index
            raise AssertionError(f"{handler} is not called where expected")

        pick_at, place_at = call_index("PickHandler"), call_index("PlaceHandler")
        self._make_function(PICK_PROLOGUE,
                            [slot_guard["source_slot"], *body[:pick_at]],
                            "Lifted from Main_program: convert the source slot to an "
                            "integer, then point robot_arm_region and robot_arm_slot at "
                            "the pick source.")
        self._make_function(PLACE_PROLOGUE,
                            [slot_guard["destination_slot"], *body[pick_at + 1 : place_at]],
                            "Lifted from Main_program: convert the destination slot to "
                            "an integer, then point robot_arm_region and robot_arm_slot "
                            "at the place destination.")

        pick_pairs = self.paired("PickHandler")
        after = [
            pair
            for index, pair in enumerate(pick_pairs)
            if index > next(i for i, (n, _) in enumerate(pick_pairs) if n.tag == "TryCatch")
        ]
        self._make_function(PICK_POSTCHECK, after,
                            "Lifted from PickHandler: confirm the gripper is holding "
                            "something once the pick returns.")

        self.crucible_selector(CRUCIBLE_PICK, "PickHandler")
        self.crucible_selector(CRUCIBLE_PLACE, "PlaceHandler")

    def _make_function(
        self, name: str, pairs: list[tuple[ET.Element, ET.Element]], description: str
    ) -> None:
        if not pairs:
            raise AssertionError(f"{name} would be empty")
        lib = SYNTHESISED[name]
        template = self.by_name["Main_program"]
        xml_block = copy.deepcopy(template)
        xml_block.find("Name").text = name
        xml_block.find("UID").text = self.full_uid(name, lib)
        if xml_block.find("Description") is not None:
            xml_block.find("Description").text = description
        holder = xml_block.find("Body/Sequence/Instructions")
        for child in list(holder):
            holder.remove(child)
        for node, _ in pairs:
            holder.append(copy.deepcopy(node))

        front_block = detach(self.definitions["Main_program"])
        front_block.set("id", self.bare_uid(name, lib))
        set_field(front_block, "FunctionBlockName", name)
        statement = front_block.find(f"{B}statement")
        set_front_chain(statement, [block for _, block in pairs])

        self.retype_calls(xml_block, front_block, lib)
        self.lifted[name] = (xml_block, front_block)

    def arm_ladder_pair(self, handler: str) -> tuple[ET.Element, ET.Element]:
        """A pick/place handler's dispatch ladder, program element beside canvas block.

        The ladder sits inside the handler's TryCatch, and the canvas keeps the whole
        else-if chain as one ``er_controls_if`` block, so there is exactly one to find.
        """
        for xml_node, front in self.paired(handler):
            if xml_node.tag != "TryCatch":
                continue
            xml_ladder = next(
                (node for node in steps(xml_node.find("TryBody")) if node.tag == "If"), None
            )
            front_ladder = next(
                (
                    block
                    for statement in front.findall(f"{B}statement")
                    for block in front_chain(statement)
                    if block.get("type") == "er_controls_if"
                ),
                None,
            )
            if xml_ladder is not None and front_ladder is not None:
                return xml_ladder, front_ladder
        raise AssertionError(f"{handler} has no ladder inside a TryCatch")

    def crucible_selector(self, name: str, handler: str) -> None:
        """Lift the four ROBOT_BASE crucible branches into one library function.

        They are consecutive in the ladder and identical but for the rack origin each
        loads, so the lift is the sub-chain itself: clone the first branch, then cut the
        else-chain loose after the last. On the canvas the whole ladder is one block with
        flat IF0/DO0..IFn/DOn slots, so the same cut is a matter of keeping four slot
        pairs and renumbering them from zero.
        """
        xml_ladder, front_ladder = self.arm_ladder_pair(handler)
        branches = [
            (xml_if, slot)
            for xml_if, _, slot in self.paired_ladder(xml_ladder, front_ladder)
            if (compare_parts(xml_if.find("Condition")) or (None, None, None))[2]
            in CRUCIBLE_REGIONS
        ]
        if len(branches) != len(CRUCIBLE_REGIONS):
            raise AssertionError(
                f"{handler}: expected {len(CRUCIBLE_REGIONS)} crucible branches, "
                f"found {[slot for _, slot in branches]}"
            )

        xml_chain = copy.deepcopy(branches[0][0])
        cursor = xml_chain
        for _ in range(len(branches) - 1):
            cursor = next(
                node for node in steps(cursor.find("ElseBody")) if node.tag == "If"
            )
        tail = cursor.find("ElseBody")
        if tail is not None:
            cursor.remove(tail)

        front_kept = [int(slot[len("DO") :]) for _, slot in branches]
        front_copy = detach(front_ladder)
        for element in list(front_copy):
            for tag, prefix in ((f"{B}value", "IF"), (f"{B}statement", "DO")):
                slot = element.get("name") or ""
                if element.tag != tag or not slot.startswith(prefix):
                    continue
                index = int(slot[len(prefix) :])
                if index in front_kept:
                    element.set("name", f"{prefix}{front_kept.index(index)}")
                else:
                    front_copy.remove(element)

        self._make_function(
            name,
            [(xml_chain, front_copy)],
            f"Lifted from {handler}: choose the rack origin for the robot's own "
            "subracks, then run the crucible move. Split out of the ladder so the "
            "origin is set in the same program that reads it.",
        )

    def home_guard(self, program: str) -> tuple[ET.Element, ET.Element]:
        """Main's own base-position check, retargeted to Home.

        BaseHandler only backed out of a station when the controller's own
        ``BasePosition`` said it was in one. Python decides that now, from an attribute
        that a manual jog or a restart can put out of step with the robot. So a goto has
        to be able to refuse: after the preamble has loaded the globals, the entry
        program asks the controller where it is and throws rather than driving at a
        station from a pose the caller did not expect.
        """
        if self.guard_template is None:
            source, station = GUARD_SOURCE
            self.guard_template = next(
                pair
                for pair in self.paired(source)
                if pair[0].tag == "If"
                and compare_parts(pair[0].find("Condition"))
                == ("BasePosition", "NEQ", station)
            )
        xml_template, front_template = self.guard_template
        message = (
            f"{program} drives from Home, but BasePosition says the base is somewhere "
            f"else. Leave the station it is in first, or correct BasePosition."
        )

        xml_guard = copy.deepcopy(xml_template)
        xml_guard.find("Condition/RHS/ValueFixed/Value").text = P.HOME
        for throw in xml_guard.iter("Throw"):
            throw.find("Message/ValueFixed/Value").text = message
        for index, node in enumerate(xml_guard.iter()):
            uid = node.find("UID")
            if uid is not None:
                uid.text = uid_from(f"guard:{program}:{index}")

        front_guard = detach(front_template)
        for index, block in enumerate(front_guard.iter(f"{B}block")):
            block.set("id", uid_from(f"guardblock:{program}:{index}"))
        compare = front_guard.find(f'{B}value[@name="IF0"]/{B}block')
        set_field(compare.find(f'{B}value[@name="B"]/{B}block'), "TextInput", P.HOME)
        for block in front_guard.iter(f"{B}block"):
            if block.get("type") == "er_throw":
                set_field(
                    block.find(f'{B}value[@name="Message"]/{B}block'),
                    "TextInput",
                    message,
                )
        return xml_guard, front_guard

    def try_catch_pair(
        self, leaf: str, program: str
    ) -> tuple[ET.Element, ET.Element]:
        """PickHandler's TryCatch with the whole ladder swapped for one call."""
        pick_pairs = self.paired("PickHandler")
        xml_try, front_try = next(
            pair for pair in pick_pairs if pair[0].tag == "TryCatch"
        )
        xml_copy = copy.deepcopy(xml_try)
        front_copy = detach(front_try)

        call_xml, call_front = self.make_call(leaf, program, f"try:{program}")
        body = xml_copy.find("TryBody")
        target = next(
            (holder for holder in body.iter("Instructions")), None
        ) or body
        for child in list(target):
            target.remove(child)
        target.append(call_xml)

        statements = front_copy.findall(f"{B}statement")
        if len(statements) != 2:
            raise AssertionError(
                f"expected a try and a catch statement, found "
                f"{[s.get('name') for s in statements]}"
            )
        set_front_chain(statements[0], [call_front])
        # The catch body already calls PickPlaceErrorHandling and rethrows; retyping it
        # for this program is all that is needed.
        self.retype_calls(xml_copy, front_copy, program)
        return xml_copy, front_copy

    # -------------------------------------------------------------------- emit

    def make_program_element(
        self, name: str, instructions: list[ET.Element], description: str
    ) -> ET.Element:
        program = ET.Element("Program")
        ET.SubElement(program, "Name").text = name
        ET.SubElement(program, "Description").text = description
        ET.SubElement(program, "UID").text = uid_from("program:" + name)
        holder = ET.SubElement(program, "Instructions")
        for node in instructions:
            holder.append(node)
        ET.SubElement(program, "IncludeProgramFuncs").text = self.includes(name)
        return program

    def includes(self, name: str) -> str:
        return ";".join(sorted(lib for lib in LIBRARIES if lib != name))

    def make_front_program(
        self, name: str, blocks: list[ET.Element]
    ) -> ET.Element:
        block = ET.Element(f"{B}block")
        block.set("type", "er_program")
        block.set("id", uid_from("program:" + name))
        block.set("deletable", "false")
        block.set("editable", "false")
        block.set("x", "0")
        block.set("y", "0")
        for field, value in (("_progName", self.includes(name)), ("TOOL_FRAME", "Manip.Flange")):
            element = ET.SubElement(block, f"{B}field")
            element.set("name", field)
            element.text = value
        statement = ET.SubElement(block, f"{B}statement")
        statement.set("name", "INSTRUCTIONS")
        set_front_chain(statement, blocks)
        return block

    def write(self, name: str, blocks: list[ET.Element], canvas: list[ET.Element]) -> None:
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)

        archive = ET.Element("Archive")
        for block in blocks:
            archive.append(block)
        ET.indent(archive, space="  ")
        ET.ElementTree(archive).write(
            folder / "program.xml", encoding="utf-8", xml_declaration=True
        )

        ET.register_namespace("", B.strip("{}"))
        root = ET.Element(f"{B}xml")
        if self.metadata is not None:
            root.append(copy.deepcopy(self.metadata))
        if self.version is not None:
            root.append(copy.deepcopy(self.version))
        if self.variables is not None:
            root.append(copy.deepcopy(self.variables))
        # Lay the definitions out in a readable column instead of Main's scatter.
        for index, block in enumerate(canvas):
            if block.get("type") == "er_function_block":
                block.set("x", str(40 + (index % 4) * 900))
                block.set("y", str(40 + (index // 4) * 1400))
            root.append(block)
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(
            folder / "frontend.xml", encoding="utf-8", xml_declaration=True
        )

    def emit_library(self, lib: str) -> int:
        blocks: list[ET.Element] = []
        canvas: list[ET.Element] = []
        names = sorted(self.members[lib])
        for name in names:
            xml_block = copy.deepcopy(self.by_name[name])
            xml_block.find("UID").text = self.full_uid(name, lib)
            front_block = detach(self.definitions[name])
            front_block.set("id", self.bare_uid(name, lib))
            self.retype_calls(xml_block, front_block, lib)
            blocks.append(xml_block)
            canvas.append(front_block)

        synthesised = [name for name, home in SYNTHESISED.items() if home == lib]
        for name in synthesised:
            xml_block, front_block = self.lifted[name]
            blocks.append(copy.deepcopy(xml_block))
            canvas.append(copy.deepcopy(front_block))

        blocks.append(
            self.make_program_element(
                lib,
                [],
                "Function library split out of Main. Not run directly; its functions "
                "are called from the Run_* entry programs.",
            )
        )
        canvas.append(self.make_front_program(lib, []))
        self.write(lib, blocks, canvas)
        return len(names) + len(synthesised)

    def entry_chain(
        self, program: str, kind: str, branch_pairs: list[tuple[ET.Element, ET.Element]]
    ) -> list[tuple[ET.Element, ET.Element]]:
        leaf = P.ENTRY_PROGRAMS[program]
        chain: list[tuple[ET.Element, ET.Element]] = [
            (copy.deepcopy(node), detach(block)) for node, block in self.preamble
        ]
        if kind == "base":
            if program in GUARDED:
                chain.append(self.home_guard(program))
            chain.extend(
                (copy.deepcopy(node), detach(block)) for node, block in branch_pairs
            )
            return chain

        chain.append(
            self.make_call(
                PICK_PROLOGUE if kind == "pick" else PLACE_PROLOGUE,
                program,
                f"{program}:prologue",
            )
        )
        if kind == "pick":
            chain.append(
                self.make_call(
                    "EnsureCalibratedWithStation", program, f"{program}:calibrate"
                )
            )
        chain.append(self.try_catch_pair(leaf, program))
        if kind == "pick":
            chain.append(
                self.make_call(PICK_POSTCHECK, program, f"{program}:postcheck")
            )
        return chain

    def emit_entry(
        self, program: str, kind: str, branch_pairs: list[tuple[ET.Element, ET.Element]]
    ) -> None:
        chain = self.entry_chain(program, kind, branch_pairs)
        entry_uid = f"{program}_{uid_from('entry:' + program)}"
        entry_bare = entry_uid[len(program) + 1 :]

        xml_block = copy.deepcopy(self.by_name["Main_program"])
        xml_block.find("Name").text = "Entry"
        xml_block.find("UID").text = entry_uid
        if xml_block.find("Description") is not None:
            xml_block.find("Description").text = (
                f"Generated from Main. Runs {P.ENTRY_PROGRAMS[program]}."
            )
        holder = xml_block.find("Body/Sequence/Instructions")
        for child in list(holder):
            holder.remove(child)
        for node, _ in chain:
            holder.append(node)

        front_block = detach(self.definitions["Main_program"])
        front_block.set("id", entry_bare)
        set_field(front_block, "FunctionBlockName", "Entry")
        set_front_chain(front_block.find(f"{B}statement"), [b for _, b in chain])

        # Base branch bodies are lifted verbatim, so their calls still name Main's
        # functions. The calls built above already point at their new homes and are
        # left alone, since their targets are not Main UIDs.
        self.retype_calls(xml_block, front_block, program)
        self._check_entry(program, xml_block)

        # The program's single instruction calls its own Entry function, the shape Main
        # uses. Built by hand because Entry is not one of Main's functions.
        call_xml = ET.Element("CallFunctionBlock")
        call_front = ET.Element(f"{B}block")
        for tag, text in (
            ("Name", "CallFunctionBlock"),
            ("UID", uid_from("entrycall:" + program)),
            ("Version", "0.1.0"),
            ("IsInitialized", "1"),
            ("FunctionBlockName", entry_uid),
        ):
            ET.SubElement(call_xml, tag).text = text
        call_front.set("type", "er_call_function_block")
        call_front.set("id", uid_from("entrycall:" + program))
        for tag, text in (
            ("FunctionBlockNameDrop", entry_bare),
            ("FunctionBlockName", entry_bare),
            ("IsSafe", "1"),
            ("IsActive", "0"),
            ("Attempts", "0"),
            ("ErrorFunctionName", ""),
            ("ErrorFunctionUid", ""),
        ):
            field = ET.SubElement(call_front, f"{B}field")
            field.set("name", tag)
            field.text = text

        blocks = [
            xml_block,
            self.make_program_element(
                program,
                [call_xml],
                f"Generated from Main. Runs {P.ENTRY_PROGRAMS[program]}.",
            ),
        ]
        canvas = [front_block, self.make_front_program(program, [call_front])]
        self.write(program, blocks, canvas)

    def _check_entry(self, program: str, block: ET.Element) -> None:
        expected = P.ENTRY_PROGRAMS[program]
        wanted = self.full_uid(expected, self.home_of(expected, program))
        targets = [
            (call.findtext("FunctionBlockName") or "").strip()
            for tag in CALL_TAGS
            for call in block.iter(tag)
        ]
        if wanted not in targets:
            raise AssertionError(
                f"{program} does not call its documented leaf {expected!r}"
            )

    # --------------------------------------------------------------------- plan

    def entry_plan(self) -> dict[str, tuple[str, list]]:
        plan: dict[str, tuple[str, list]] = {}
        collapsed: dict[str, int] = {}

        def add(program: str, kind: str, pairs: list) -> None:
            if program in plan:
                collapsed[program] = collapsed.get(program, 1) + 1
                return
            plan[program] = (kind, pairs)

        # Base: walk BaseHandler's two ladders in both files at once.
        base_pairs = self.paired("BaseHandler")
        outer_xml, outer_front = base_pairs[0]
        guard = self.paired_body(outer_xml, outer_front, "IfBody", "DO0")
        ladders = [pair for pair in guard if pair[0].tag == "If"]

        leave_root = self.paired_body(ladders[0][0], ladders[0][1], "IfBody", "DO0")
        leave_first = next(pair for pair in leave_root if pair[0].tag == "If")
        for xml_if, front_if, slot in self.paired_ladder(*leave_first):
            body = self.paired_body(xml_if, front_if, "IfBody", slot)
            for var, _, value in composite_values(xml_if.find("Condition")):
                if var != "BasePosition":
                    continue
                program = P.OUTFROM.get(value)
                # Charging, ChargingNoWait and the furnace calibration pose all just
                # drive Home, which the goto ladder already produced.
                if program and program not in P.GOTO.values():
                    add(program, "base", body)

        for xml_if, front_if, slot in self.paired_ladder(*ladders[1]):
            body = self.paired_body(xml_if, front_if, "IfBody", slot)
            for var, _, value in composite_values(xml_if.find("Condition")):
                if var == "target_base_position" and value in P.GOTO:
                    add(P.GOTO[value], "base", body)

        # Pick and place only need the region/slot key; the body is one call, which the
        # entry chain rebuilds around its own TryCatch.
        for kind, handler, resolve in (
            ("pick", "PickHandler", P.resolve_pick),
            ("place", "PlaceHandler", P.resolve_place),
        ):
            for branch in arm_branches(handler, self.uid_to_name, self.by_name):
                try:
                    program, _ = resolve(branch["region"], branch["slot"] or "0")
                except P.UnsupportedRoute as error:
                    self.notes.append(
                        f"{kind} branch {branch['region']}/{branch['slot']}: {error}"
                    )
                    continue
                add(program, kind, [])

        for program, count in sorted(collapsed.items()):
            self.notes.append(
                f"{program} covers {count} ladder branches with the same leaf"
            )
        return plan

    # ---------------------------------------------------------------------- run

    def write_references(self) -> None:
        """Main's 24 references, once, beside the archives rather than inside each.

        ``save_program_as`` does not carry references at all, and the UI import path
        does not need a copy per program: they are app-scoped and keyed by Uid, and
        every archive here reuses Main's Uids. So one file serves all 73, and a
        controller that has ever had Main installed already has them.
        """
        source = MAIN_DIR / "data.xml"
        if source.is_file():
            shutil.copyfile(source, OUT / "data.xml")

    def run(self) -> int:
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        self.build_lifted()
        for lib in dict.fromkeys(SYNTHESISED.values()):
            names = [name for name, home in SYNTHESISED.items() if home == lib]
            print(f"lifted into {lib}: {', '.join(names)}")

        print("\nlibraries:")
        for lib in LIBRARIES:
            print(f"  {lib:<16} {self.emit_library(lib)} functions")

        plan = self.entry_plan()
        for program, (kind, pairs) in sorted(plan.items()):
            self.emit_entry(program, kind, pairs)
        print(f"\nentry programs: {len(plan)}")

        missing = sorted(set(P.ENTRY_PROGRAMS) - set(plan))
        extra = sorted(set(plan) - set(P.ENTRY_PROGRAMS))
        if missing:
            print(f"\nNO LADDER BRANCH FOUND ({len(missing)}):")
            for name in missing:
                print(f"    {name}")
        if extra:
            print(f"\nNOT IN THE TABLE ({len(extra)}):")
            for name in extra:
                print(f"    {name}")
        if self.notes:
            print("\nnotes:")
            for note in self.notes:
                print(f"  - {note}")

        self.write_references()
        print(f"\ntotal archives: {len(LIBRARIES) + len(plan)}  ->  {OUT}")
        print("references: data.xml written once, shared by all of them")
        return 1 if (missing or extra) else 0


if __name__ == "__main__":
    sys.exit(Splitter().run())
