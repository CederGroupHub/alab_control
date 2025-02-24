import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import time
import threading

from pymodbus.client.sync import ModbusSerialClient as ModbusClient
from pymodbus.exceptions import ModbusException

from alab_control.dh_robotic_gripper.dh_robotic_gripper import GripperController, RotationDirection
from alab_control.dh_linear_rail.dh_linear_rail import LinearRailController
from alab_control.ohaus_scale.ohaus_scale_gpss import OhausScale 
from alab_control.gripper_shaker.gripper_shaker import GripperShaker

from enum import Enum

class XRDPrepController:
    def __init__(self):
        self.gripper = GripperController(port="COM9")
        self.linear_rail = LinearRailController(port="COM6")
        self.balance = OhausScale("192.168.1.62")   #("192.168.1.62"), ohaus.gpss
        self.shaker = GripperShaker("192.168.1.58")
        
        self.currnet_mass = None
        self.stop_mass_thread = False
        self.stop_positioning = False
        self.lock = threading.Lock()
        
    def initialize_grip(self):
        self.gripper.initialize()
        self.gripper.save_configuration()
        self.gripper.rotate(direction=RotationDirection.CLOCKWISE,
                            deg=0,
                            speed=5,
                            force=25,
                            check_gripper=False)
        
    def initialize_rail(self):
        self.linear_rail.initialize(wait=True)
    
    def move_rail(self, distance):
        self.linear_rail.move_to(distance, max_acceleration = 50, wait=True)
    
    def rotate_gripper(self, deg, speed, force):
        self.gripper.rotate(direction=RotationDirection.CLOCKWISE,
                            deg=deg, 
                            speed=speed,
                            force=force,
                            check_gripper=False)
    
    def gripping(self, open_p):
        self.gripper.open_to(speed_percentage=50, force_percentage=100, position=open_p*10)
    
    def shake_gripper(self, count=2, v_time=800):
        self.shaker.repeat_motor(count, v_time) #(shaking time, shaking delay)
        print("shaking")    
    
    def positioning_powder(self, angle: int = 40, speed: int = 3, force: int = 25):
        self.rotate_gripper(-180 - angle, speed, force)
        self.rotate_gripper(-180 + angle, speed, force)
        self.rotate_gripper(-180, speed, force)

    def initialize(self): 
        ### Do initializing XRDPrepController
        
        self.gripper.initialize()
        self.gripper.save_configuration()
        self.rotate_gripper(0, 5, 25)
        
        self.linear_rail.initialize(wait=True)
        print("Initiallize finished")
        self.gripping(45)
        self.move_rail(0)
        time.sleep(3)
            
    def place_to_balance(self): 
        ### Do after place vial on the Gripper
        ### Have to place XRD sample holder first
        
        self.gripping(25)
        self.rotate_gripper(-180,3,25)
        self.positioning_powder(60, 5, 25)
        self.positioning_powder(45, 3, 25)
        time.sleep(1)
        self.move_rail(74)

    def mass_reading_thread(self):
        ### Read mass continuously
        while not self.stop_mass_thread:
            try:
                new_mass = self.balance.get_mass_in_mg("IP")
                with self.lock:
                    self.current_mass = new_mass
            except:
                print("Mass reading failed. Retrying...")
            time.sleep(0.05)  # Mass reading time

    def start_mass_monitoring(self):
        self.stop_mass_thread = False
        self.mass_thread = threading.Thread(target=self.mass_reading_thread, daemon=True)
        self.mass_thread.start()

    def stop_mass_monitoring(self):
        self.stop_mass_thread = True
        self.mass_thread.join()
            
    def dispensing_powder(self, amount, max_tries: int = 16, max_time: float = 5, time_stamp=0.02):
        ### Dispensing powder on the XRD holder or crucible in target amount.
        ### When dispensing XRD powder on the holder, type amount = 120
        if amount < 10:
            print(f"Target mass is too low to accurately dispense: {amount} mg")
            return None
        elif amount < 250:
            max_time = 0.5 + (amount//50)*0.5
            max_tries = 10

        self.rotate_gripper(-180, 5, 25)

        initial_mass = self.balance.get_mass_in_mg()
        if initial_mass < 1000:
            raise RuntimeError('Please check place of the XRD holder on the scaler')
        print('Mass of XRD holder: ', initial_mass)
        print('Target mass is :', amount, ' mg')

        self.start_mass_monitoring()  # Start mass reading thread

        retry_count = 0
        while retry_count < max_tries:            
            print(f"\n Attempt {retry_count + 1}/{max_tries} started...")
            if retry_count % 4 == 0 and retry_count > 0: # Re-align the powder on to the sieve
                if amount < 250:
                    max_time = max_time*2 # increase time
                else:
                    max_time += 1
                self.move_rail(0)
                time.sleep(0.2)
                self.positioning_powder(70, 5, 25)
                self.positioning_powder(45, 3, 25)
                time.sleep(0.2)
                self.move_rail(74)

            angle = -185 + (retry_count % 2) * 10
            self.rotate_gripper(angle, 3, 25)
            start_time = time.time()

            self.shaker.start_motor()  # Start vibration motor

            while time.time() - start_time < max_time:
                with self.lock:
                    if self.current_mass is None or not isinstance(self.current_mass, (int, float)):
                        print("Error: Invalid mass reading. Stopping process.")
                        self.shaker.stop_motor()
                        self.stop_mass_monitoring()
                        raise RuntimeError("Mass reading failed. Please check the balance connection.")
                    remain_mass = self.current_mass - initial_mass

                print(f"Current mass is: {remain_mass} mg")

                if remain_mass >= amount - 2:
                    print("Target mass reached. Stopping shaker motor.")
                    self.shaker.stop_motor()

                    print(time.time() - start_time)
                    time.sleep(1)

                    with self.lock:
                        final_mass = self.balance.get_mass_in_mg("SP")  # Read final mass
                    print(f"Final mass of XRD holder: {final_mass}")

                    self.stop_mass_monitoring()  # Finish mass reading thread
                    self.move_rail(0)
                    time.sleep(0.2)
                    self.rotate_gripper(0, 1, 25)
                    self.gripping(45)
                    return

                time.sleep(time_stamp)  # processing cycle to prevent CPU processing overheating

            retry_count += 1
            self.shaker.stop_motor()
            print(f"Trying... ({retry_count}/{max_tries})")

            if retry_count < max_tries:
                time.sleep(2) if amount < 220 else time.sleep(5)
            else:
                print("Maximum attempts reached. Stopping process.")
                time.sleep(1)

                with self.lock:
                    final_mass = self.balance.get_mass_in_mg("SP")
                print(f"Final mass of XRD holder: {final_mass}")

                self.stop_mass_monitoring()  # Finish mass reading thread
                self.move_rail(0)
                time.sleep(0.2)
                self.rotate_gripper(0, 1, 25)
                self.gripping(45)
                return
        
# Example        
if __name__ == "__main__":
    xrd_dispenser = XRDPrepController()
    xrd_dispenser.initialize()
    # move xrd_holder on the balance
    # move xrd_vial on the gripper
    xrd_dispenser.place_to_balance()
    xrd_dispenser.dispensing_powder(amount = 250)
    # remove xrd_holder from the balance
    # remove xrd_vial from the gripper
