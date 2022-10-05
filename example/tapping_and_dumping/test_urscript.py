from alab_control.robot_arm_ur5e.robots import Dummy


if __name__ == '__main__':
    dummy = Dummy(ip="192.168.0.23")
    # with open("test.urscript", "w", encoding="utf-8") as f:
    #     program = dummy._ssh_client.read_program("test_urscript.script")
    #     program = [line for line in program.splitlines() if line and not line.strip(" ").startswith("$")]
    #     f.write("\n".join(program))
    for _ in range(10):
        dummy._secondary_client.run_program(
            dummy._ssh_client.read_program("shaking.script", header_file_name="empty.script"),
            True
        )
    dummy.close()
