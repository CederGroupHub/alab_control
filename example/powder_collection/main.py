import logging
import re
import random
logging.basicConfig(level="INFO")

import time
from typing import Tuple
from alab_control.robot_arm_ur5e.robots import CharDummy
from alab_control.shaker import Shaker
from alab_control.ball_dispenser import BallDispenser
from alab_control.capper import Capper
from alab_control.ohaus_scale import OhausScale
from alab_control.diffractometer_aeris import Aeris
from alab_control.cap_dispenser import CapDispenser


class ALab:
    def __init__(self) -> None:
        self.dummy = CharDummy("192.168.0.23")
        self.shaker = Shaker("192.168.0.32")
        self.ball_dispenser = BallDispenser("192.168.0.33")
        self.capper = Capper("192.168.0.51")
        self.cap_dispenser = CapDispenser("192.168.0.31")
        self.balance = OhausScale("192.168.0.24")
        self.aeris = Aeris(debug=False)

    def sample_processing(self):
        initial_weight = self.weighing()
        print(f"Initial mass is {initial_weight} mg.")
        self.decapping("B")
        self.shaking_crucible()
        self.tapping()
        self.capping("B")
        final_weight = self.weighing()
        print(f"Final mass is {final_weight} mg.")
        print(f"In total {initial_weight - final_weight} mg powder is collected.")
        self.shaking_vial()
    
    def capping(self, cap: str = "B"):
        self.dummy.run_programs([
            "move_vial_dumping_capper.urp",
            f"pick_cap_{cap}.urp",
            self.capper.close,
            "capping.urp",
            self.capper.open,
            "move_vial_capper_dumping.urp",
        ])
    
    def decapping(self, cap: str = "B"):
        self.dummy.run_programs([
            "move_vial_dumping_capper.urp",
            self.capper.close,
            "decapping.urp",
            self.capper.open,
            f"place_cap_{cap}.urp" if cap != "dispose" else "dispose.urp",
            "move_vial_capper_dumping.urp",
        ])

    def change_cap(self, old_, new_):
        self.dummy.run_programs([
            "move_vial_dumping_capper.urp",
            self.capper.close,
        ])
        if random.random() < 1/4:
            self.dummy.run_program("calibriate_capping.urp")
        
        self.dummy.run_programs([
            "decapping.urp",
            self.capper.open,
            f"place_cap_{old_}.urp" if old_ != "dispose" else "dispose.urp",
        ])
        self.dummy.run_programs([
            f"pick_cap_{new_}.urp",
            self.capper.close,
        ])
        self.dummy.run_programs([
            "capping.urp",
            self.capper.open,
            "move_vial_capper_dumping.urp",
        ])

    def shaking_crucible(self):
        self.dummy.run_programs([
            "vertical_to_horizonal.urp",
            # add balls to crucible
            "pick_cru_B.urp",
            "before_ball_dispensing.urp",
            self.ball_dispenser.dispense_balls,
            "after_ball_dispensing.urp",
            "place_cru_B.urp",

            # add cap to crucible
            "horizonal_to_vertical.urp",
            lambda: self.cap_dispenser.open(1),
            "pick_cap_dispenser_A.urp",
            lambda: self.cap_dispenser.close(1),
            "place_cap_cru_B.urp",
            "vertical_to_horizonal.urp",

            # send to shaker
            "pick_cru_B.urp",
            "before_shaking_cru.urp",
            lambda: self.shaker.grab_and_shaking(duration_sec=120),
            "after_shaking_cru.urp",
            "place_cru_B.urp",

            # remove cap from crucible
            "horizonal_to_vertical.urp",
            "pick_cap_cru_B.urp",
            "dispose.urp",
        ])

    def shaking_vial(self):
        self.dummy.run_programs([
            "vertical_to_horizonal.urp",
            "pick_vial_dumping_station.urp",
            "before_shaking_vial.urp",
            lambda: self.shaker.grab_and_shaking(duration_sec=120),
            "after_shaking_vial.urp",
            "place_vial_dumping_station.urp",
            "horizonal_to_vertical.urp",
        ])

    def dumping(self): 
        self.dummy.run_programs([
            "pick_cru_B.urp",
            "dumping.urp",
            "place_cru_B.urp",
        ])

    def tapping(self):
        self.dummy.run_programs([
            "vertical_to_horizonal.urp",
            # send vial to tapping station
            "pick_vial_dumping_station.urp",
            "place_vial_tapping_station.urp",

            # send crucible to shaker
            "pick_cru_B.urp",
            "before_tapping.urp",
            lambda: self.shaker.shaking(duration_sec=15),
            "after_tapping.urp",
            "place_cru_B.urp",

            # take the vial back to dumping station
            "pick_vial_tapping_station.urp",
            "place_vial_dumping_station.urp",
            "horizonal_to_vertical.urp",
        ])

    def xrd_powder_dispensing(self) -> Tuple[int, bool]:
        self.dummy.run_program("vertical_to_horizonal.urp")
        self.dummy.run_program("pick_vial_dumping_station_reverse.urp")
        self.dummy.run_program("before_weighing_vial.urp")
        time.sleep(3)
        initial_weight = self.balance.get_mass_in_mg()
        self.dummy.run_program("after_weighing_vial.urp")
        current_weight = initial_weight
        last_weight = 0

        trial_time = 0
        while initial_weight - current_weight < 100 and trial_time < 4 and abs(current_weight - last_weight) >= 8:
            trial_time += 1
            self.dummy.run_program("xrd_powder_dispensing.urp")

            if trial_time > 1 and initial_weight - current_weight < 75:
                for _ in range(trial_time - 1):
                    self.dummy.run_program("xrd_powder_dispensing.urp")

            self.dummy.run_program("before_weighing_vial.urp")
            time.sleep(3)
            last_weight = current_weight
            current_weight = self.balance.get_mass_in_mg()
            print(f"Current mass in XRD holder: {initial_weight - current_weight}")
            self.dummy.run_program("after_weighing_vial.urp")
        
        self.dummy.run_program("place_vial_dumping_station_reverse.urp")
        self.dummy.run_program("horizonal_to_vertical.urp")

        return initial_weight - current_weight, initial_weight - current_weight >= 100

    def xrd_sample_flattening(self):
        self.cap_dispenser.open(3)
        self.dummy.run_programs([
            "pick_cap_dispenser_C.urp",
            "xrd_sample_flattening.urp",
            "dispose.urp",
        ])
        self.cap_dispenser.close(3)

    def weighing(self) -> int:
        self.dummy.run_programs([
            "vertical_to_horizonal.urp",
            "pick_cru_B.urp",
            "before_weighing.urp",
        ])
        time.sleep(3)
        mass_in_mg = self.balance.get_mass_in_mg()
        self.dummy.run_programs([
            "after_weighing.urp",
            "place_cru_B.urp",
            "horizonal_to_vertical.urp",
        ])
        return mass_in_mg

    def scan_code(self) -> str:
        self.dummy.run_program("take_photo.urp")
        installation_variables = self.dummy.ssh.read_file("/programs/default.variables")
        code = re.search(r'(?<=current_code=").*(?=")', installation_variables).group()
        if not code:
            raise ValueError("Cannot find code")
        return code

import cv2

cam = cv2.VideoCapture(1)


def take_photo(name):
    ret, frame = cam.read()
    cv2.imwrite(name, frame)



if __name__ == "__main__":
    from pathlib import Path
    from tqdm import tqdm 
    alab = ALab()
    print(alab.scan_code())
    # alab.sample_processing()

    # for i in range(1, 21):
    #     alab.dummy.run_programs([
    #         "pick_transfer_rack_B.auto.urp",
    #         f"place_buffer_rack_{i}.auto.urp",
    #         f"pick_buffer_rack_{i}.auto.urp",
    #         "place_transfer_rack_B.auto.urp",
    #     ])

    # for i in range(1, 9):
    #     if i!=1:
    #         alab.dummy.run_programs([
    #             f"pick_vial_rack_A_{i}.auto.urp",
    #             f"place_dumping_station.auto.urp",
    #         ])
    #         alab.dummy.run_programs([
    #             f"pick_transfer_rack_{i}.auto.urp",
    #             "place_transfer_rack_B.auto.urp",
    #         ])
    #         alab.sample_processing()

    #         alab.dummy.run_programs([
    #             f"pick_dumping_station.auto.urp",
    #             f"place_vial_rack_A_{i}.auto.urp",
    #         ])
    #         alab.dummy.run_programs([
    #             "pick_transfer_rack_B.auto.urp",
    #             f"place_vial_rack_C_{i}.auto.urp",
    #         ])
    #     else:
    #         alab.dummy.run_program(
    #             f"place_vial_rack_C_{i}.auto.urp",
    #         )
    # alab.capping("A")

    # aeris_i = None
    # aeris_sample_id = None

    # sample_ids = {
    #     # 1: "A1",
    #     # 2: "A2",
    #     # 3: "A3",
    #     # 4: "A4",
    #     # 5: "A5",

    #     # 6: "B1",
    #     # 7: "B2",
    #     # 8: "B3",
    #     # 9: "B4",
    #     # 10: "B5",

    #     11: "C1",
    #     12: "C2",
    #     13: "C3",
    #     14: "C4",
    #     15: "C5",
    # }

    # for i, sample_id in sample_ids.items():
    #     if i != 2:
    #         alab.dummy.run_programs([
    #             f"pick_vial_rack_B_{i}.auto.urp",
    #             f"place_dumping_station.auto.urp",
    #         ])

    #         alab.cap_dispenser.open(2)
    #         alab.dummy.run_programs([
    #             "pick_cap_dispenser_B.urp",
    #             "place_cap_A.urp",
    #         ])
    #         alab.cap_dispenser.close(2)
                    
    #         alab.dummy.run_programs([
    #             f"pick_xrd_holder_rack_{i}.auto.urp",
    #             "place_xrd_dispense_station.urp"
    #         ])

    #         alab.change_cap("B", "A")

    #         mass, result = alab.xrd_powder_dispensing()

    #         print(mass, result)

    #     alab.xrd_sample_flattening()

    #     while alab.aeris.xrd_is_busy:
    #         time.sleep(2)
    #     if aeris_sample_id is not None:
    #         time.sleep(5)  # wait for the gripper to fully stop
    #         result = alab.aeris.load_scan_results(f"NNBO_{aeris_sample_id}_auto")
    #         alab.aeris.remove_by_slot(1)

    #         alab.dummy.run_programs([
    #             "pick_xrd_holder_machine.urp",
    #             f"place_xrd_holder_rack_{aeris_i}.auto.urp"
    #         ])

    #     alab.dummy.run_programs([
    #         "pick_xrd_dispense_station.urp",
    #         "place_xrd_holder_machine.urp",
    #     ])

    #     aeris_i = i
    #     aeris_sample_id = sample_id
    #     alab.aeris.add(sample_id=f"NNBO_{sample_id}_auto", loc=1, default_program="10-100_8-minutes")
    #     alab.aeris.scan(sample_id=f"NNBO_{sample_id}_auto", program="10-100_8-minutes")

    #     alab.change_cap("dispose", "B")
    #     alab.dummy.run_programs([
    #         f"pick_dumping_station.auto.urp",
    #         f"place_vial_rack_B_{i}.auto.urp",
    #     ])

    # while alab.aeris.xrd_is_busy:
    #     time.sleep(2)
    # if aeris_sample_id is not None:
    #     time.sleep(5)  # wait for the gripper to fully stop
    #     result = alab.aeris.load_scan_results(f"NNBO_{aeris_sample_id}_auto")
    #     alab.aeris.remove_by_slot(1)

    #     alab.dummy.run_programs([
    #         "pick_xrd_holder_machine.urp",
    #         f"place_xrd_holder_rack_{aeris_i}.auto.urp"
    #     ])

    # for i in range(0, 1):
    #     # alab.capping("B")
    #     alab.cap_dispenser.open(2)
    #     alab.dummy.run_programs([
    #         "pick_cap_dispenser_B.urp",
    #         "place_cap_A.urp",
    #     ])
    #     alab.cap_dispenser.close(2)
    #     alab.dummy.run_programs([
    #         f"pick_vial_rack_C_{i+1}.auto.urp",
    #         f"place_dumping_station.auto.urp",
    #     ])
    #     alab.capping("A")
    #     # alab.dummy.run_programs([
    #     #     "pick_cap_A.urp",
    #     #     "dispose.urp",
    #     # ])  
    #     alab.dummy.run_programs([
    #         f"pick_dumping_station.auto.urp",
    #         f"place_vial_rack_B_{i+1}.auto.urp",
    #     ])

    # for i in range(17, 18):
    #     alab.dummy.run_programs([
    #         # f"pick_xrd_holder_rack_{i}.auto.script",
    #         # "place_xrd_dispense_station.urp",
    #         "horizonal_to_vertical.urp",
    #         "pick_xrd_dispense_station.urp",
    #         # lambda: alab.aeris.add(sample_id=f"empty_{i}_auto", loc=1, default_program="10-140_2-min"),
    #         "place_xrd_holder_machine.urp",
    #         # lambda: alab.aeris.scan_and_return_results(sample_id=f"empty_{i}_auto", program="10-140_2-min"),
    #         "pick_xrd_holder_machine.urp",
    #         # lambda: alab.aeris.remove(sample_id=f"empty_{i}_auto"),
    #         "place_xrd_dispense_station.urp",
    #         "vertical_to_horizonal.urp",

    #         # f"place_xrd_holder_rack_{i}.auto.script"
    #     ])
    # alab.decapping("B")
    # alab.dummy.run_programs([
    #     "horizonal_to_vertical.urp",
    #     "pick_transfer_rack_1.auto.script",
    #     "place_transfer_rack_B.auto.script",
    #     "pick_vial_rack_B_1.auto.script",
    #     "place_dumping_station.auto.script",
    #     "vertical_to_horizonal.urp",
    # ])
    # alab.sample_processing()
    # alab.xrd_powder_dispensing()
    # alab.xrd_sample_flattening()
    # alab.capping(cap="A")
    # alab.decapping(cap="A")
    # alab.xrd_powder_dispensing()

    # for _ in tqdm(range(50)):
        # alab.capping(cap="A")
        # take_photo((Path(__file__).parent / f"vial_5_{_}.jpg").as_posix())
        # alab.decapping(cap="A")
