"""Read and compose the Ability backend XML that the execution engine actually runs.

Ability keeps two documents per program. ``frontend.xml`` is the Blockly canvas.
``program.xml`` is the backend archive, and it is the one the controller executes: a flat
``<Archive>`` of ``<FunctionBlock>`` elements plus a single ``<Program>`` root.

Three things about that archive matter here:

- ``CallFunctionBlock`` refers to a function by UID, not by name. The UIDs are prefixed
  with the program's internal name, ``Main_test``, which is not the name in the UI.
- Every base move maintains ``BasePosition`` itself. ``HomeBase`` sets it to 'Unknown',
  saves, drives, sets 'Home', saves again. So invoking one of these functions directly
  keeps the variable honest, and an interrupted move leaves 'Unknown' rather than a
  confident lie.
- A function is self-contained apart from the functions it calls, so a subset archive
  holding the transitive closure of one function is enough to execute it.

This module only reads the export on disk and builds instruction elements. Nothing here
talks to the robot; :mod:`session` does that.

The export is a 14 MB file that does not belong in a Python package, so its location is
configuration: set ``MIR250_PROGRAM_ARCHIVE`` to the path of ``Main/program.xml``, or pass
a path to :class:`ProgramArchive`. Nothing imports it at module scope, so the rest of the
driver works without it -- only per-block invocation needs the archive.
"""

from __future__ import annotations

import itertools
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Iterable

#: Environment variable naming the exported Ability backend archive.
ARCHIVE_PATH_ENV = "MIR250_PROGRAM_ARCHIVE"

# Every instruction carries a UID. The controller only needs them to be unique inside
# the payload, and prefixing ours keeps a Python-issued instruction identifiable if one
# ever turns up in a controller log.
UID_PREFIX = "py"


def default_archive_path() -> Path:
    """The configured archive path, without checking that it exists."""
    configured = os.environ.get(ARCHIVE_PATH_ENV)
    if configured:
        return Path(configured)
    return Path.home() / ".alab_control" / "mir250" / "program.xml"


def compact(element: ET.Element) -> str:
    """Serialise without the export's inherited indentation.

    The export nests indentation so deeply that a single function block serialises to
    tens of kilobytes of spaces, which matters when it goes over a websocket.
    """
    raw = ET.tostring(element, encoding="unicode")
    return re.sub(r"\s+", " ", re.sub(r">\s+<", "><", raw)).strip()


def _text(parent: ET.Element, tag: str, value: str = "") -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = value
    return child


def _value_fixed(parent: ET.Element, tag: str, value: str, type_name: str) -> None:
    holder = ET.SubElement(parent, tag)
    fixed = ET.SubElement(holder, "ValueFixed")
    _text(fixed, "Name", "ValueFixed")
    _text(fixed, "Version", "1.0.0")
    _text(fixed, "Type", type_name)
    _text(fixed, "Value", value)


class ProgramArchive:
    """The backend archive of an exported Ability program."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_archive_path()
        if not self.path.is_file():
            raise FileNotFoundError(
                f"the exported Ability archive is not at {self.path}. Export Main from the "
                f"controller and point {ARCHIVE_PATH_ENV} at its program.xml; this is only "
                "needed for per-block invocation through the programming interface"
            )
        self.root = ET.parse(self.path).getroot()
        if self.root.tag != "Archive":
            raise ValueError(
                f"{self.path} is not an Ability archive, root is <{self.root.tag}>"
            )
        self.functions: dict[str, ET.Element] = {}
        self.by_uid: dict[str, ET.Element] = {}
        for block in self.root.findall("FunctionBlock"):
            name = (block.findtext("Name") or "").strip()
            uid = (block.findtext("UID") or "").strip()
            if name:
                self.functions[name] = block
            if uid:
                self.by_uid[uid] = block
        program = self.root.find("Program")
        self.program_name = (
            (program.findtext("Name") or "").strip() if program is not None else ""
        )

    def uid(self, name: str) -> str:
        block = self.functions.get(name)
        if block is None:
            raise KeyError(f"no function named {name!r} in {self.path.name}")
        return (block.findtext("UID") or "").strip()

    def name_of(self, uid: str) -> str:
        block = self.by_uid.get(uid)
        return (block.findtext("Name") or "").strip() if block is not None else ""

    def calls(self, name: str) -> list[str]:
        """Names of the functions one function calls, in document order."""
        block = self.functions.get(name)
        if block is None:
            raise KeyError(f"no function named {name!r}")
        seen: list[str] = []
        for call in block.iter("CallFunctionBlock"):
            called = self.name_of((call.findtext("FunctionBlockName") or "").strip())
            if called and called not in seen:
                seen.append(called)
        return seen

    def closure(self, names: Iterable[str]) -> list[str]:
        """A function plus everything it can reach, so a subset archive is complete."""
        ordered: list[str] = []
        pending = list(names)
        while pending:
            name = pending.pop(0)
            if name in ordered or name not in self.functions:
                continue
            ordered.append(name)
            pending.extend(self.calls(name))
        return ordered

    def instruction_kinds(self) -> dict[str, int]:
        """Every instruction element the engine runs here, and how often.

        This is the vocabulary available to ``execute_instruction``: anything the export
        contains is something the controller demonstrably accepts. Instructions live
        directly under an ``<Instructions>`` holder, which is what separates them from
        the value and variable elements nested inside them.
        """
        counts: Counter[str] = Counter()
        for holder in self.root.iter("Instructions"):
            for child in holder:
                counts[child.tag] += 1
        return dict(counts.most_common())

    def value_types(self) -> dict[str, int]:
        """The ``ValueFixed`` types in use, which is the real type vocabulary."""
        counts: Counter[str] = Counter()
        for fixed in self.root.iter("ValueFixed"):
            counts[(fixed.findtext("Type") or "").strip() or "(none)"] += 1
        return dict(counts.most_common())

    def function_xml(self, name: str) -> str:
        block = self.functions.get(name)
        if block is None:
            raise KeyError(f"no function named {name!r} in {self.path.name}")
        return compact(block)

    def archive_xml(self, names: Iterable[str] | None = None) -> str:
        """The whole archive, or one holding just the closure of the named functions.

        A subset keeps the payload to kilobytes instead of 14 MB, which matters when
        the transport is a websocket and the controller is parsing it synchronously.
        """
        if names is None:
            return compact(self.root)
        keep = set(self.closure(names))
        subset = ET.Element("Archive")
        for child in self.root:
            if child.tag != "FunctionBlock":
                subset.append(child)
            elif (child.findtext("Name") or "").strip() in keep:
                subset.append(child)
        return compact(subset)


_uid_counter = itertools.count(1)


def _instruction(tag: str, uid_hint: str) -> ET.Element:
    # Unique within the payload is the requirement, and a compound Sequence can hold two
    # instructions of the same kind, so the counter is not decoration.
    element = ET.Element(tag)
    _text(element, "Name", tag)
    _text(element, "UID", f"{UID_PREFIX}_{uid_hint}_{next(_uid_counter)}")
    _text(element, "Version", "0.1.0")
    _text(element, "IsInitialized", "1")
    return element


def wait_instruction(seconds: float) -> ET.Element:
    """A Wait, which is the only instruction that provably does nothing.

    Used as the probe when checking whether the controller will execute a
    Python-supplied instruction at all: no motion, no variable touched, no I/O.
    """
    element = _instruction("Wait", "wait")
    _value_fixed(element, "Time", f"{seconds * 1000:.0f}", "Double")
    return element


def call_instruction(archive: ProgramArchive, function_name: str) -> ET.Element:
    """A CallFunctionBlock naming one of the archive's functions by UID."""
    element = _instruction("CallFunctionBlock", "call")
    _text(element, "FunctionBlockName", archive.uid(function_name))
    return element


def assign_instruction(
    name: str, value: str, type_name: str = "String"
) -> ET.Element:
    """Assign a value to a program variable, without persisting it."""
    element = _instruction("Assign", "assign")
    lhs = ET.SubElement(element, "LHS")
    variable = ET.SubElement(lhs, "Variable")
    _text(variable, "Name", name)
    _text(variable, "Version", "1.0.0")
    _value_fixed(element, "RHS", value, type_name)
    return element


def assign_from_variable_instruction(name: str, source: str) -> ET.Element:
    """Copy one variable into another.

    The way to observe a program argument: arguments arrive as variables of the running
    program, so copying one into a persisted variable is how its value gets out.
    """
    element = _instruction("Assign", "copy")
    for side, variable_name in (("LHS", name), ("RHS", source)):
        holder = ET.SubElement(element, side)
        variable = ET.SubElement(holder, "Variable")
        _text(variable, "Name", variable_name)
        _text(variable, "Version", "1.0.0")
    return element


def save_variable_instruction(name: str, is_global: bool = True) -> ET.Element:
    """Persist a variable, the instruction Main uses to make BasePosition survive."""
    element = _instruction("SaveVariable", "save")
    variable = ET.SubElement(element, "Variable")
    _text(variable, "Name", name)
    _text(variable, "Version", "1.0.0")
    _text(element, "Global", "1" if is_global else "0")
    return element


def sequence_instruction(instructions: Iterable[ET.Element]) -> ET.Element:
    """Several instructions as one instruction.

    The archive uses ``Sequence`` this way inside ``Instructions`` holders, so it is an
    instruction in its own right rather than only a function body. That makes a
    multi-step run possible in a single ``execute_instruction`` call, which is the
    difference between a Python step and a Python program. Unlike other instructions a
    real one carries no UID, and it does carry ``IsBlocking``, so this matches the export
    field for field.
    """
    element = ET.Element("Sequence")
    _text(element, "Name", "Sequence")
    _text(element, "Version", "0.1.0")
    _text(element, "IsBlocking", "true")
    _text(element, "IsInitialized", "1")
    holder = ET.SubElement(element, "Instructions")
    for instruction in instructions:
        holder.append(instruction)
    return element


def function_block(name: str, instructions: Iterable[ET.Element]) -> ET.Element:
    """Wrap instructions in a function block, matching the export's shape exactly.

    The fields look redundant but the controller rejects a block that is missing any
    of them, and silently misbehaves if IsInitialized is absent.
    """
    block = ET.Element("FunctionBlock")
    _text(block, "Name", name)
    _text(block, "Description", "void")
    _text(block, "UID", f"{UID_PREFIX}_{name}")
    body = ET.SubElement(block, "Body")
    sequence = ET.SubElement(body, "Sequence")
    _text(sequence, "Name", "Sequence")
    _text(sequence, "Version", "0.1.0")
    _text(sequence, "IsInitialized", "true")
    _text(sequence, "IsErrorFunctionActive", "0")
    _text(sequence, "ErrorFunctionName")
    _text(sequence, "ErrorFunctionUid")
    _text(sequence, "RetryAttempts", "0")
    holder = ET.SubElement(sequence, "Instructions")
    for instruction in instructions:
        holder.append(instruction)
    return block


def program_archive(
    program_name: str,
    instructions: Iterable[ET.Element],
    functions: Iterable[ET.Element] = (),
) -> str:
    """A complete, self-contained program archive built in Python.

    Same shape as the export: an ``<Archive>`` of ``<FunctionBlock>`` elements plus one
    ``<Program>``. Copying the function blocks in, rather than referring to Main through
    ``IncludeProgramFuncs``, keeps the program standalone and means nothing about it
    depends on Main staying as it is.
    """
    archive = ET.Element("Archive")
    for function in functions:
        archive.append(function)
    program = ET.SubElement(archive, "Program")
    _text(program, "Name", program_name)
    _text(program, "Description", "void")
    _text(program, "UID", f"{UID_PREFIX}_{program_name}")
    holder = ET.SubElement(program, "Instructions")
    for instruction in instructions:
        holder.append(instruction)
    ET.SubElement(program, "IncludeProgramFuncs")
    return compact(archive)
