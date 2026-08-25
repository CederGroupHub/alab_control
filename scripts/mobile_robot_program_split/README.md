# Splitting Main into per-station programs

The Ability controller used to run one Blockly program, `Main`: 48k lines, 125 function
blocks, and three if-ladders totalling about 4000 lines of string matching that chose
which movement to perform from five string arguments. This folder turns that into nine
function libraries plus one small program per movement, and checks the result.

The routing that replaced the ladders is **not** here. It ships in the package, at
[`alab_control/mobile_robot_arm/programs.py`](../../alab_control/mobile_robot_arm/programs.py),
because it is needed at runtime to decide which program to load. This folder is
build-time only: nothing in it runs in the lab.

## Input

`Main`'s export -- `program.xml`, `frontend.xml`, `data.xml` -- which is not in the repo.
It is a vendor export, and the whole point of the split is to stop editing it. The path
defaults to the Desktop folder it was exported to on the lab PC; set `MAIN_EXPORT` to the
folder holding those three files anywhere else.

## The toolchain

Run in this order. Each is safe to rerun; the generator wipes its output first.

| Script | What it does |
| --- | --- |
| `assignment.py` | The map: which of Main's functions belongs to which library. Data, not a script; edit this to move a function. |
| `validate.py` | Checks the map before generating: every function assigned, every cross-library call legal, no scratch variable crossing a library boundary. |
| `routes_from_xml.py` | Walks the three ladders and reports every branch and the leaf it calls. The generator lifts branch bodies through this, and `programs.py` is diffed against it so the table and the Blockly cannot drift apart. |
| `generator.py` | Main to 73 archives, `program.xml` and `frontend.xml` built in lockstep. |
| `audit.py` | Checks the output: parses, every call resolves, no archive still names Main, no orphan functions, each canvas agrees with its program instruction for instruction, and no program reads a scratch variable that nothing in it writes. |
| `dryrun.py` | Resolves every route AlabOS can ask for against the archives on disk, so a missing program shows up here rather than on the cell. |
| `smoketest.py` | Deploys the nine libraries and one entry program and runs one real movement, to prove cross-program calls and the argument path on hardware. Run this before `deploy.py`. |
| `deploy.py` | Uploads the archives over the `save_program_as` ROS service, libraries first. `--dry-run` first. |

## Output

`split_programs/<Name>/{program.xml,frontend.xml}`, committed, plus one shared
`data.xml`. It is shared rather than copied into each folder because references are
app-scoped and keyed by Uid, and every archive reuses Main's Uids: the programs resolve
against the references already on the controller, which is also why the split shares one
calibration with `Main` instead of forking it. The single copy matters only for a
controller that has never had `Main` installed.

Nothing in the output is hand-authored. Every instruction is lifted out of `Main`, with
one exception: each `Run_GoTo_*` except `Run_GoTo_Home` opens with a check that
`BasePosition` is `Home`, throwing if not. That is Main's own guard from
`Out from IXRD`, retargeted -- necessary because deciding whether to back out of a
station moved to Python, so the controller needs to be able to refuse.

## What has to stay in the same program

`Main` was one program, so any function could read what any other had written. Split
across programs that is no longer free, and the split has no precedent to copy: `Main`
never used `CallIncProgFunction` once, so nothing in the export says whether a
non-persisted value survives a call into another program's functions. So the rule here is
that it must never have to. A variable saved with `SaveVariable` travels through the
controller's global store and can be read anywhere; anything else has to be written and
read inside one program, and `audit.py` fails if it is not.

Three things follow, and each one was a real bug before it was a rule:

- The argument dictionary is read by the entry program, because the controller hands
  arguments to whichever program it loads. That is why the preamble is inlined into all
  64 entry programs rather than called in `Shared`.
- Each prologue carries its own slot-to-integer conversion, because `int_source_slot` and
  `int_destination_slot` are never saved.
- `On_Robot` owns `PickCrucibleFromRobotBase` and `PlaceCrucibleOnRobotBase`, the
  four-branch choice of rack origin lifted out of the handlers, because `GridOrigin` is
  never saved either and `GridCompute` reads it.

## `analysis/`

The scripts that worked out the answers above: which function touches which variable,
which are orphaned, what each ladder branch really does, how the canvas encodes an
else-if chain. Kept because they are the evidence for `assignment.py` and for the
oddities recorded in `programs.py`, and rerunning one beats re-deriving it. Not needed to
regenerate.
