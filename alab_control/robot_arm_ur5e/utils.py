import re


def get_header(file_string: str):
    return re.search(
        r"# begin: URCap Installation Node.*# end: URCap Installation Node",
        file_string,
        re.DOTALL
    ).group(0)


def replace_header(orginal_file: str, new_header: str):
    return re.sub(
        r"# begin: URCap Installation Node.*# end: URCap Installation Node",
        new_header,
        orginal_file,
        flags=re.DOTALL
    )


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
