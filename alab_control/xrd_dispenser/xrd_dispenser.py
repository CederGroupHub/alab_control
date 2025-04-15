from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from pydantic import BaseModel

from alab_control.dh_linear_rail.dh_linear_rail import LinearRailController
from alab_control.dh_robotic_gripper.dh_robotic_gripper import (
    GripperController,
    RotationMode,
)
from alab_control.gripper_shaker.gripper_shaker import GripperShaker
from alab_control.ohaus_scale.ohaus_scale_gpss import OhausScale

logger = logging.getLogger(__name__)


class XRDPrepController:
    def __init__(self, gripper_port, rail_port, balance_ip, shaker_ip):
        self.gripper = GripperController(port=gripper_port)
        self.linear_rail = LinearRailController(port=rail_port)
        self.balance = OhausScale(balance_ip)
        self.shaker = GripperShaker(shaker_ip)

    def move_rail_forward(self):
        # Move to balance
        self.linear_rail.move_to(74, max_acceleration=50, wait=True)
        time.sleep(0.5)

    def move_rail_backward(self):
        # Move back to initial position
        self.linear_rail.move_to(0, max_acceleration=50, wait=True)
        time.sleep(0.5)

    def face_to_balance(self):
        # rotate the vial to face to the balance (downward)
        self.gripper.rotate(
            deg=270, speed=5, force=25, check_gripper=False, mode=RotationMode.ABSOLUTE
        )

    def face_to_robot(self):
        # rotate the vial to face to the robot (upward)
        self.gripper.rotate(
            deg=90, speed=5, force=25, check_gripper=False, mode=RotationMode.ABSOLUTE
        )

    def close_gripper(self):
        self.gripper.open_to(speed_percentage=50, force_percentage=100, position=0)

    def open_gripper(self):
        self.gripper.open_to(speed_percentage=50, force_percentage=100, position=500)

    def shake_powder_off_sieve(self):
        """
        Shake the gripper once (for 3 second) to remove powder on the sieve
        """
        with self.shaker.motor_on():
            time.sleep(3)

    def distribute_powder(self, angle: int = 45, speed: int = 3, force: int = 25):
        """
        Rotate left and right to distribute powder evenly on the sieve
        """
        for angle_ in [-angle, angle, angle, -angle]:
            self.gripper.rotate(
                deg=angle_,
                speed=speed,
                force=force,
                check_gripper=False,
                mode=RotationMode.RELATIVE,
            )

    def get_weight_on_balance(self, mode: Literal["quick", "precise"] = "precise"):
        """
        Get the weight on the balance
        """
        if mode == "quick":
            return self.balance.get_mass_in_mg("IP")
        elif mode == "precise":
            result = self.balance.get_mass_in_mg("SP")
            if result is None:
                logger.info(
                    "Failed to get stable mass from the balance, return quick result"
                )
                return self.get_weight_on_balance(mode="quick")
            return result
        else:
            raise ValueError("Invalid mode. Use 'quick' or 'precise'.")

    def initialize(self):
        # Do initializing XRDPrepController
        self.gripper.initialize()
        self.gripper.save_configuration()
        self.face_to_robot()
        self.linear_rail.initialize(wait=True)
        logger.info("Initialization finished")
        self.open_gripper()

    def prepare_dispensing(self):
        """
        Do after place vial on the Gripper
        """
        self.close_gripper()
        self.move_rail_forward()
        self.face_to_balance()

    def after_dispensing(self):
        """
        Move the vial back for unloading
        """
        self.move_rail_backward()
        self.face_to_robot()
        self.shake_powder_off_sieve()
        self.open_gripper()

    def get_rotate_gripper_thread(
        self, angle: int = 5
    ) -> tuple[threading.Thread, threading.Event]:
        """
        Rotate the gripper to a certain angle. This can help distribute the powder
        during shaking
        """
        stop_event = threading.Event()

        def keep_rotating_gripper():
            self.gripper.rotate(
                deg=angle,
                speed=5,
                force=25,
                check_gripper=False,
                mode=RotationMode.RELATIVE,
            )
            counter = 0
            last_rotation_time = time.time()
            while not stop_event.is_set():
                time.sleep(0.05)
                if time.time() - last_rotation_time > 1:
                    counter += 1
                    last_rotation_time = time.time()
                    self.gripper.rotate(
                        deg=angle * 2 * (-1 if counter % 2 else 1),
                        speed=5,
                        force=25,
                        check_gripper=False,
                        mode=RotationMode.RELATIVE,
                    )
            else:
                # rotate back to original position based on current counter
                self.gripper.rotate(
                    deg=angle * (1 if counter % 2 else -1),
                    speed=5,
                    force=25,
                    check_gripper=False,
                    mode=RotationMode.RELATIVE,
                )

        thread = threading.Thread(target=keep_rotating_gripper)
        return thread, stop_event

    def dispensing_powder(
        self,
        target_mass,
        max_time: float = 10,
        tolerance: int = 10,
        angle_offset: int = 10,
    ):
        """
        Move the vial onto the balance, dispense powder, and return the mass

        Args:
            target_mass: target mass to dispense
            max_time: maximum time to dispense the powder
            tolerance: tolerance for the mass (default to -10mg). If the mass is
                within the tolerance, mark it as finished
            angle_offset: angle to rotate the gripper while dispensing
        """
        initial_mass = self.get_weight_on_balance(mode="precise")
        logger.info(f"Mass of XRD holder: {initial_mass} mg")
        logger.info(f"Target mass is : {target_mass} mg")

        # move the vial to the balance
        self.prepare_dispensing()

        retry_count = 0
        finished = False
        last_time_weight = initial_mass
        while not finished:
            retry_count += 1
            logger.info(f"Attempt {retry_count} started...")

            start_time = time.time()
            gripper_rotating_thread, stop_event = self.get_rotate_gripper_thread(
                angle=angle_offset
            )
            try:
                gripper_rotating_thread.start()
                with self.shaker.motor_on():
                    while time.time() - start_time < max_time:
                        current_mass = self.get_weight_on_balance(mode="quick")
                        remain_mass = current_mass - initial_mass

                        # if the mass is within the tolerance, mark it as finished
                        if remain_mass >= target_mass - tolerance:
                            finished = True
                            break
                        # add a short delay to avoid spamming the balance
                        time.sleep(0.05)
            finally:
                # ensure the gripper stops rotating
                stop_event.set()
                gripper_rotating_thread.join()

            if current_mass - last_time_weight <= tolerance:
                # if the mass is increasing, reset the retry count
                finished = True

            logger.info(f"Current mass: {current_mass} mg")

        self.after_dispensing()
        final_mass = self.get_weight_on_balance(mode="precise")
        logger.info(f"Final mass of XRD holder: {final_mass} mg")

        mass_reached = (final_mass - initial_mass) >= target_mass - tolerance
        if not mass_reached:
            logger.info("Stop due to no more increase in mass can be made.")
        else:
            logger.info("Stop due to target mass reached.")

        return {
            "initial_mass": initial_mass,
            "final_mass": final_mass,
            "target_mass": target_mass,
            "mass_reached": mass_reached,
            "remain_mass": final_mass - initial_mass,
        }


if __name__ == "__main__":
    xrd_dispenser = XRDPrepController(
        gripper_port="/dev/tty.usbserial-BG005CHD",
        rail_port="/dev/tty.usbserial-BG004CS1",
        balance_ip="192.168.1.62",
        shaker_ip="192.168.1.58",
    )
    xrd_dispenser.initialize()
