import copy
import json
import time
from pathlib import Path
from pprint import pprint
from random import shuffle
from traceback import print_exc

import pymongo
from jinja2 import Environment, FileSystemLoader, StrictUndefined

program_collection = pymongo.MongoClient()["robot_arm"]["program"]


def generate_home_urscript(template_name="home.script", name="initial_rack_to_box_furnace_rack_1",
                           go_home=True, gripper_model="hande", robot_model="ur5e"):
    env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                      extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)
    template = env.get_template(template_name)

    config = {
        "go_home": go_home,
        "gripper_model": gripper_model,
        "robot_model": robot_model,
    }

    program_doc = program_collection.find_one({"name": name})

    config["home_mid_poses"] = [pos["pose"] for pos in program_doc["home_trans"]]
    config["home_mid_qnears"] = [pos["joint"] for pos in program_doc["home_trans"]]

    config["start_pose"] = program_doc["initial_position"]["pose"]
    config["start_qnear"] = program_doc["initial_position"]["joint"]

    script = template.render(**config)

    return script


def generate_urscript(from_, to_,
                      template_name="pick_place.script",
                      name="initial_rack_to_box_furnace_rack_1",
                      approach_distance_mm=60,
                      # speed_factor=1.,
                      gripper_model="hande",
                      robot_model="ur5e",

                      for_local=False):
    env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                      extensions=["jinja2_workarounds.MultiLineInclude"], undefined=StrictUndefined)
    template = env.get_template(template_name)

    config = {
        "speed": 0.3,
        "approach_distance_mm": approach_distance_mm,
        "gripper_model": gripper_model,
        "robot_model": robot_model,
    }

    program_doc = program_collection.find_one({"name": name})

    config["start_pose"] = program_doc["initial_position"]["pose"]
    config["start_qnear"] = program_doc["initial_position"]["joint"]

    config["trans_poses"] = [pos["pose"] for pos in program_doc["transition_waypoints"]]
    config["trans_qnears"] = [pos["joint"] for pos in program_doc["transition_waypoints"]]

    start_positions = {pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
                       for pos in program_doc["start_positions"]}
    config["pick_pose"] = start_positions[from_]["pose"]
    config["pick_qnear"] = start_positions[from_]["joint"]

    end_positions = {pos["name"]: {"pose": pos["pose"], "joint": pos["joint"]}
                     for pos in program_doc["end_positions"]}
    config["place_pose"] = end_positions[to_]["pose"]
    config["place_qnear"] = end_positions[to_]["joint"]

    script = template.render(**config)

    if for_local:
        script = script.split("\n")
        script = [line for line in script if not line.strip(" ").startswith("$")]
        script = "\n".join(script) + "\n\nunnamed()\n"
    return script


if __name__ == '__main__':
    # with open("test.script", "w", encoding="utf-8") as f:
    #     f.write(generate_urscript())

    import urx

    robot = urx.Robot("192.168.0.23")

    try:
        # config_generate(robot)
        # exit(1)
        name = "buffer_rack"
        type_ = "crucible"
        # with open(r"templates/Pick_BFRACK_L.script", "r", encoding="utf-8") as f:
        #     program = f.read()

        # robot.send_program(program)
        # #     program = [line for line in f.readlines() if not line.strip(" ").startswith("$")]
        # # with open(r"temp.script", "w", encoding="utf-8") as f:
        # #     f.write("".join(program))
        #
        # exit(0)

        i = input("Enter the approach distance (mm): ")
        program_collection.update_one({"name": name}, {"$set": {
            "approach_distance_mm": float(i),
            "type": type_,
        }}, upsert=True)

        i = input("Enter gripper open distance (mm): ")
        program_collection.update_one({"name": name}, {"$set": {
            "gripper_open_mm": float(i),
        }}, upsert=True)

        input("Press Enter to set start point:")
        program_collection.update_one({
            "name": name
        }, {"$set": {"start_pos": {
            "pose": robot.getl(),
            "joint": robot.getj(),
        }}}, upsert=True)
        
        i = input("Press Enter to set trans, press -1 to stop:")
        while i != "-1":
            program_collection.update_one({
                "name": name
            }, {"$push": {"transition_waypoints": {
                "pose": robot.getl(),
                "joint": robot.getj(),
            }}}, upsert=True)
            i = input("Press Enter to set trans, press -1 to stop:")

        for pos in range(1, 21):
            input(f"Press enter to set position for {pos}:")
            program_collection.update_one({
                "name": name
            }, {"$push": {"pick_position": {
                "name": f"{pos}",
                "pose": robot.getl(),
                "joint": robot.getj(),
            }}}, upsert=True)

        # i = input("Press Enter to set trans, press -1 to stop:")
        # while i != "-1":
        #     program_collection.update_one({
        #         "name": name
        #     }, {"$push": {"transition_waypoints": {
        #         "pose": robot.getl(),
        #         "joint": robot.getj(),
        #     }}}, upsert=True)
        #     i = input("Press Enter to set trans, press -1 to stop:")

        # for pos in [str(i+1) for i in range(16)]:
        #     input(f"Press enter to set position for {pos}:")
        #     program_collection.update_one({
        #         "name": name
        #     }, {"$push": {"end_positions": {
        #         "name": f"transfer_rack/{pos}",
        #         "pose": robot.getl(),
        #         "joint": robot.getj(),
        #     }}}, upsert=True)

        commnads = [
            # {
            #     "name": "initial_rack_to_box_furnace_rack_1",
            #     "start": ["4A", "4C", "5B", "6A", "6C", "7B", "8A", "8C"],
            #     "end": [f"D{i + 1}" for i in range(8)],
            # },
            # {
            #     "name": "initial_rack_to_box_furnace_rack_2",
            #     "start": ["3A", "3C", "4B", "5A", "5C", "6B", "7A", "7C"],
            #     "end": [f"C{i + 1}" for i in range(8)],
            # },
            # {
            #     "name": "box_furnace_rack_to_intermediate_rack_1",
            #     "start": [f"D{i+1}" for i in range(8)],
            #     "end": [f"D{i+1}" for i in range(8)],
            # "start": ["D8"],
            # "end": ["D8"]
            # },
            # {
            #     "name": "box_furnace_rack_to_intermediate_rack_2",
            #     # "start": [f"C{i+1}" for i in range(8)],
            #     # "end": [f"C{i+1}" for i in range(8)],
            #     "start": ["C8"],
            #     "end": ["C8"]
            # }
        ]

        # if not robot.is_program_running():
        #     robot.send_program(generate_home_urscript(name=name, go_home=False, template_name="home.script"))
        #     # print(generate_home_urscript(name=name, go_home=True, template_name="home.script"))
        #
        # time.sleep(1)
        # while robot.is_program_running():
        #     time.sleep(0.5)
        #
        # starts = ["1", "2", "3", "4", "5", "8"]
        # ends = ["1", "2", "5", "8", "12", "13", "14", "16"]
        #
        # for start, end in zip(starts, ends):
        #     if not robot.is_program_running():
        #         robot.send_program(generate_urscript(from_=start, to_=end,
        #                                              name=name, template_name="pick_place.script"))
        #     time.sleep(1)
        #     while robot.is_program_running():
        #         time.sleep(0.5)
        #
        # if not robot.is_program_running():
        #     robot.send_program(generate_home_urscript(name=name, go_home=True, template_name="home.script"))
        # time.sleep(1)
        # while robot.is_program_running():
        #     time.sleep(0.5)

    except Exception as e:
        print_exc()
    finally:
        robot.close()

    # with open("test.script", "w", encoding="utf-8") as f:
    #     f.write(generate_urscript(for_local=True))
