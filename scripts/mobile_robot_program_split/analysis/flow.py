"""For the scratch variables that cross a library boundary, is the flow real?

A variable that every touching function writes before reading is a local temporary
that merely shares a name (URAction's `returnVal` is the obvious case). A variable
written in one function and only read in another is genuine cross-function state,
and that is what cannot cross a program boundary unpersisted.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from assignment import ASSIGNMENT  # noqa: E402

MAIN = Path(
    r"C:\Users\Ceder-ALAB\Desktop\Mobile Robot Testing and Validation\Main\program.xml"
)

SUSPECT = [
    "GridOrigin",
    "LABMAN_pickplace_stage",
    "TagCalibrationSuccessful",
    "TagCalibrationTrialCount",
    "isReachable",
    "offset_x",
    "offset_y",
    "returnVal",
    "x_dim",
]

# Elements whose child <Variable> is a destination rather than a source.
WRITE_PARENTS = ("LHS", "Response", "Result", "Output")


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

    writes: dict[str, set[str]] = defaultdict(set)
    reads: dict[str, set[str]] = defaultdict(set)

    for var in root.iter("Variable"):
        name = (var.findtext("Name") or "").strip()
        if name not in SUSPECT:
            continue
        fn = owner(var)
        parent = parent_of.get(var)
        parent_tag = parent.tag if parent is not None else ""
        grandparent = parent_of.get(parent) if parent is not None else None
        gp_tag = grandparent.tag if grandparent is not None else ""
        if parent_tag in WRITE_PARENTS or gp_tag in ("SaveVariable",):
            writes[name].add(fn)
        else:
            reads[name].add(fn)

    for name in SUSPECT:
        w, r = writes[name], reads[name]
        read_only = sorted(r - w)
        print(f"\n{name}")
        print(f"  writes in {len(w)} functions, reads in {len(r)}")
        if not read_only:
            print("  LOCAL: every function that reads it also writes it")
            continue
        print(f"  reads WITHOUT a local write in {len(read_only)} functions:")
        for fn in read_only:
            print(f"      {ASSIGNMENT.get(fn, '?'):<16} {fn}")
        producer_libs = {ASSIGNMENT.get(f) for f in w} - {None}
        consumer_libs = {ASSIGNMENT.get(f) for f in read_only} - {None}
        crossing = producer_libs != consumer_libs or len(producer_libs | consumer_libs) > 1
        print(f"  producers in {sorted(producer_libs)}")
        print(f"  pure consumers in {sorted(consumer_libs)}")
        print(f"  -> {'CROSSES a boundary' if crossing else 'contained'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
