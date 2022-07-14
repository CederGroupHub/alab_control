import copy
import json
import time
from pathlib import Path
from pprint import pprint
from random import shuffle
from traceback import print_exc

import pymongo
from jinja2 import Environment, FileSystemLoader

program_collection = pymongo.MongoClient()["robot_arm"]["program"]

CONFIG = {'approach_distance_mm': 60,
 'gripper_model': 'hande',
 'pick_pose': [-0.12549926327008884,
               0.39342369527722654,
               0.5030413037205943,
               -3.1409541322303056,
               -0.04714793720283418,
               0.00034538212053022597],
 'pick_qnear': [2.212435722351074,
                -1.3321272891810914,
                -1.7433353662490845,
                -1.6370851002135218,
                1.5775736570358276,
                0.6078218221664429],
 'place_pose': [0.5850504754473321,
                -0.12999070927455336,
                0.41946066937187776,
                -2.273440878810931,
                2.1677954892153837,
                -0.00037663918200610144],
 'place_qnear': [0.0077750831842422485,
                 -1.7998243770995082,
                 -1.4920159578323364,
                 -1.4206988227418442,
                 1.5783843994140625,
                 -0.04153949419130498],
 'robot_model': 'ur5e',
 'start_pose': [-0.15301598758040008,
                0.4304377910303712,
                0.6036941602477394,
                -3.1304436430764713,
                -0.2614621847810168,
                0.0002443007729901085],
 'start_qnear': [2.212259292602539,
                 -1.4826811116984864,
                 -1.3580958843231201,
                 -1.8718415699400843,
                 1.5771973133087158,
                 0.4696464240550995],
 'trans_poses': [[-0.06433766654781559,
                  0.22882039743261542,
                  0.6632956162598951,
                  -3.1410088629382753,
                  -0.047290174824788034,
                  0.0002475393716305308],
                 [-0.06432728810730233,
                  0.22881938154930867,
                  0.6633275772069135,
                  -3.140917020593618,
                  -0.04715174870334781,
                  0.00039660481597710343],
                 [0.23715319169514226,
                  -0.016175502732646535,
                  0.6632836429334725,
                  -1.8490841624986276,
                  2.539516418535204,
                  -0.00028122218243437384],
                 [0.6321172693572303,
                  -0.10179063363173645,
                  0.5763400530873363,
                  -2.273503184952177,
                  2.1677507707714665,
                  -0.00031021915727397605]],
 'trans_qnears': [[2.450446128845215,
                   -1.0326696199229737,
                   -1.468000888824463,
                   -2.21197046856069,
                   1.5750019550323486,
                   0.8421702980995178],
                  [2.450421094894409,
                   -1.0326610964587708,
                   -1.4679439067840576,
                   -2.211902757684225,
                   1.5749926567077637,
                   0.8422327637672424],
                  [0.5374669432640076,
                   -1.03267856061969,
                   -1.4680246114730835,
                   -2.2119747600951136,
                   1.5749143362045288,
                   0.8421866297721863],
                  [0.052115973085165024,
                   -1.9356352291502894,
                   -0.9080538749694824,
                   -1.868899484673971,
                   1.5777212381362915,
                   -1.1269246236622621e-05]]}


def generate_urscript(from_, to_,
                      template_name="pick_place.script",
                      name="initial_rack_to_box_furnace_rack_1",
                      approach_distance_mm=60,
                      # speed_factor=1.,
                      gripper_model="hande",
                      robot_model="ur5e",

                      for_local=False):
    env = Environment(loader=FileSystemLoader((Path(__file__).parent / "templates").as_posix()),
                      extensions=["jinja2_workarounds.MultiLineInclude"])
    template = env.get_template(template_name)

    config = {
        # "speed_factor": speed_factor,
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


def config_generate(robot):
    config = copy.deepcopy(CONFIG)
    input("Press Enter to set start point:")
    config["start_pose"] = robot.getl()
    config["start_qnear"] = robot.getj()

    input("Press Enter to set pick point:")
    config["pick_pose"] = robot.getl()
    config["pick_qnear"] = robot.getj()

    i = input("Press Enter to set trans, press -1 to stop:")
    config["trans_poses"] = []
    config["trans_qnears"] = []
    while i != "-1":
        config["trans_poses"].append(robot.getl())
        config["trans_qnears"].append(robot.getj())
        i = input("Press Enter to set trans, press -1 to stop:")

    input("Press Enter to set place point:")
    config["place_pose"] = robot.getl()
    config["place_qnear"] = robot.getj()

    robot.close()

    print("Done!")
    pprint(config)
    with open("test.config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=1)


if __name__ == '__main__':
    # with open("test.script", "w", encoding="utf-8") as f:
    #     f.write(generate_urscript())

    import urx
    robot = urx.Robot("192.168.0.22")

    try:
        # config_generate(robot)
        # exit(1)

        # input("Press Enter to set start point:")
        # program_collection.update_one({
        #     "name": "initial_rack_to_box_furnace_rack_1"
        # }, {"$set": {"initial_position": {
        #     "pose": robot.getl(),
        #     "joint": robot.getj(),
        # }}}, upsert=True)

        # i = input("Press Enter to set trans, press -1 to stop:")
        # while i != "-1":
        #     program_collection.update_one({
        #         "name": "initial_rack_to_box_furnace_rack_1"
        #     }, {"$push": {"transition_waypoints": {
        #         "pose": robot.getl(),
        #         "joint": robot.getj(),
        #     }}}, upsert=True)
        #     i = input("Press Enter to set trans, press -1 to stop:")

        # for pos in ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"):
        #     input(f"Press enter to set position for {pos}:")
        #     program_collection.update_one({
        #         "name": "initial_rack_to_box_furnace_rack_1"
        #     }, {"$push": {"end_positions": {
        #         "name": pos,
        #         "pose": robot.getl(),
        #         "joint": robot.getj(),
        #     }}}, upsert=True)

        starts = ["4A", "4C", "5B", "6A", "6C", "7B", "8A", "8C"]
        ends = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]
        # shuffle(starts)
        # shuffle(ends)

        # starts = ["4A"]
        # ends = ["D4"]
        for start, end in zip(starts, ends):
            if not robot.is_program_running():
                robot.send_program(generate_urscript(from_=start, to_=end))
            time.sleep(1)
            while robot.is_program_running():
                time.sleep(0.5)
    except Exception as e:
        print_exc()
    finally:
        robot.close()

    # with open("test.script", "w", encoding="utf-8") as f:
    #     f.write(generate_urscript(for_local=True))
