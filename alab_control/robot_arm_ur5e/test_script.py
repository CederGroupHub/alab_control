from pathlib import Path

from sympy import root

from alab_control.robot_arm_ur5e.robots import CharDummy
from alab_control.robot_arm_ur5e.utils import get_header, replace_header
import pymongo
from jinja2 import Environment, FileSystemLoader, StrictUndefined

db = pymongo.MongoClient()["robot_arm"]
program = db["program"]

robot = CharDummy("192.168.0.23")
robot.set_speed(1)


def make_config(program_doc, position_name):
    config = {
        "approach_distance_mm": program_doc["approach_distance_mm"],
        "gripper_open_mm": program_doc["gripper_open_mm"],
    }

    config["start_pose"] = program_doc["start_pos"]["pose"]
    config["start_qnear"] = program_doc["start_pos"]["joint"]

    config["trans_poses"] = [pos["pose"] for pos in program_doc["transition_waypoints"]]
    config["trans_qnears"] = [pos["joint"] for pos in program_doc["transition_waypoints"]]

    pick_positions = {pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
                    for pos in program_doc["pick_position"]}
    config["pick_pose"] = pick_positions[position_name]["pose"]
    config["pick_qnear"] = pick_positions[position_name]["joint"]
    return config


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
        config = make_config(rack_c, f"{i}")
        config["name"] = f"pick_vial_rack_C_{i}"
        program = replace_header(pick_template.render(**config), header)
        robot.run_program(program)

        # # place 
        # if i != 1:
        config = make_config(dumping, "1")
        config["name"] = f"place_dumping_1"
        program = replace_header(place_template.render(**config), header)
        robot.run_program(program)

        config = make_config(dumping, "1")
        config["name"] = f"pick_dumping_1"
        program = replace_header(pick_template.render(**config), header)
        robot.run_program(program)

        config = make_config(rack_c, f"{i}")
        config["name"] = f"place_vial_rack_C_{i}"
        program = replace_header(place_template.render(**config), header)
        robot.run_program(program)
