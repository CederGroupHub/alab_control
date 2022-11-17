from pathlib import Path

import pymongo
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from alab_control.robot_arm_ur5e.robots import CharDummy
from alab_control.robot_arm_ur5e.utils import make_template_config

programs_collection = pymongo.MongoClient()["robot_arm"]["program"]

env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                  extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)
place_template = env.get_template("place.script")
pick_template = env.get_template("pick.script")
urp_template = env.get_template("urp_template")

robot = CharDummy("192.168.0.23")


def remove_urscript_label(urscript: str) -> str:
    urscript_lines = urscript.splitlines()
    urscript_lines = [line for line in urscript_lines if not line.strip().startswith("$")]
    return "\n".join(urscript_lines)


for program_doc in programs_collection.find({}):
    position_names = [pick_position["name"] for pick_position in program_doc["pick_position"]]
    for position_name in position_names:
        config = make_template_config(program_doc, position_name)
        
        name = f"pick_{program_doc['name']}" + (f"_{position_name}" if len(position_names) > 1 else "")
        config["name"] = name
        pick_program = pick_template.render(**config)
        pick_program = remove_urscript_label(pick_program)
        robot.ssh.write_program(name + ".auto.script", pick_program)

        urp_program = urp_template.render({
            "program_path": "/programs/" + name + ".auto.script",
            "program_string": pick_program,
        })
        robot.ssh.compress_write_program(name + ".auto.urp", urp_program)

        name = f"place_{program_doc['name']}" + (f"_{position_name}" if len(position_names) > 1 else "")
        config["name"] = name
        place_program = place_template.render(**config)
        place_program = remove_urscript_label(place_program)
        robot.ssh.write_program(name + ".auto.script", place_program)

        urp_program = urp_template.render({
            "program_path": "/programs/" + name + ".auto.script",
            "program_string": place_program,
        })
        robot.ssh.compress_write_program(name + ".auto.urp", urp_program)