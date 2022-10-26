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

robot = CharDummy("192.168.0.23")

for program_doc in programs_collection.find({}):
    position_names = {pick_position["name"] for pick_position in program_doc["pick_position"]}
    for position_name in position_names:
        config = make_template_config(program_doc, position_name)
        config["name"] = f"pick_{program_doc['name']}" + f"_{position_name}" if len(position_name) > 1 else ""
        pick_program = pick_template.render(**config)
        robot.ssh.write_program(pick_program, f"pick_{program_doc['name']}" +
                                              f"_{position_name}" if len(position_name) > 1 else "")
        config["name"] = f"place_{program_doc['name']}" + f"_{position_name}" if len(position_name) > 1 else ""
        place_program = place_template.render(**config)
        robot.ssh.write_program(place_program, f"place_{program_doc['name']}" +
                                               f"_{position_name}" if len(position_name) > 1 else "")
