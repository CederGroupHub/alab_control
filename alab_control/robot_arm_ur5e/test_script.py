from pathlib import Path

from sympy import root

from alab_control.robot_arm_ur5e.robots import CharDummy
from alab_control.robot_arm_ur5e.utils import get_header, replace_header, make_template_config
import pymongo
from jinja2 import Environment, FileSystemLoader, StrictUndefined

db = pymongo.MongoClient()["robot_arm"]
program = db["program"]

robot = CharDummy("192.168.0.23")
robot.set_speed(1)


if __name__ == "__main__":
    # transfer_rack = program.find_one({"name": "transfer_rack"})
    # env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
    #                   extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)
    # place_template = env.get_template("place.script")
    # pick_template = env.get_template("pick.script")

    # header = get_header(robot.ssh.read_program("empty.script"))
    # robot.set_speed(1)
    # for i in range(4, 13):
    #     # pick
    #     config = make_config(transfer_rack, f"{i}")
    #     config["name"] = f"pick_transfer_rack_{i}"
    #     program = replace_header(pick_template.render(**config), header)
    #     robot.run_program(program)

    #     # place
    #     config = make_config(transfer_rack, "B")
    #     config["name"] = f"place_transfer_rack_B"
    #     program = replace_header(place_template.render(**config), header)
    #     robot.run_program(program)

    #     config = make_config(transfer_rack, "B")
    #     config["name"] = f"place_transfer_rack_B"
    #     program = replace_header(pick_template.render(**config), header)
    #     robot.run_program(program)

    #     # place
    #     config = make_config(transfer_rack, f"{i}")
    #     config["name"] = f"place_transfer_rack_{i}"
    #     program = replace_header(place_template.render(**config), header)
    #     robot.run_program(program)     

    rack_c = program.find_one({"name": "vial_rack_B"})
    dumping = program.find_one({"name": "dumping_station"})
    env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                      extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)
    place_template = env.get_template("place.script")
    pick_template = env.get_template("pick.script")

    header = get_header(robot.ssh.read_program("empty.script"))
    
    for i in range(1, 17):
        # pick
        config = make_template_config(rack_c, f"{i}")
        config["name"] = f"pick_vial_rack_C_{i}"
        program = replace_header(pick_template.render(**config), header)
        robot.run_program(program)

        # # place 
        # if i != 1:
        config = make_template_config(dumping, "1")
        config["name"] = f"place_dumping_1"
        program = replace_header(place_template.render(**config), header)
        robot.run_program(program)

        config = make_template_config(dumping, "1")
        config["name"] = f"pick_dumping_1"
        program = replace_header(pick_template.render(**config), header)
        robot.run_program(program)

        config = make_template_config(rack_c, f"{i}")
        config["name"] = f"place_vial_rack_C_{i}"
        program = replace_header(place_template.render(**config), header)
        robot.run_program(program)
