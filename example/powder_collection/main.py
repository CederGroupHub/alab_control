import time
from typing import Tuple
from alab_control.robot_arm_ur5e.robots import CharDummy
from alab_control.shaker import Shaker
from alab_control.ball_dispenser import BallDispenser
from alab_control.capper import Capper
from alab_control.ohaus_scale import OhausScale


class ALab:
    def __init__(self) -> None:
        self.dummy = CharDummy("192.168.0.23")
        self.shaker = Shaker("192.168.0.32")
        self.ball_dispenser = BallDispenser("192.168.0.33")
        self.capper = Capper("192.168.0.51")
        self.balance = OhausScale("192.168.0.24")

    def sample_processing(self):
        initial_weight = self.weighing()
        print(f"Initial mass is {initial_weight} mg.")
        self.decapping()
        self.shaking_crucible()
        self.dumping()
        self.tapping()
        self.capping()
        final_weight = self.weighing()
        print(f"Final mass is {final_weight} mg.")
        print(f"In total {0 - final_weight} mg powder is collected.")
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
            f"place_cap_{cap}.urp",
            "move_vial_capper_dumping.urp",
        ])

    def shaking_crucible(self):
        self.dummy.run_programs([
            # add balls to crucible
            "pick_cru_B.urp",
            "before_ball_dispensing.urp",
            self.ball_dispenser.dispense_balls,
            "after_ball_dispensing.urp",
            "place_cru_B.urp",

            # add cap to crucible
            "horizonal_to_vertical.urp",
            "pick_cap_B.urp",
            "place_cap_cru_B.urp",
            "vertical_to_horizonal.urp",

            # send to shaker
            "pick_cru_B.urp",
            "before_shaking_cru.urp",
            lambda: self.shaker.grab_and_shaking(duration_sec=20),
            "after_shaking_cru.urp",
            "place_cru_B.urp",

            # remove cap from crucible
            "horizonal_to_vertical.urp",
            "pick_cap_cru_B.urp",
            "place_cap_B.urp",
            "vertical_to_horizonal.urp",
        ])

    def shaking_vial(self):
        self.dummy.run_programs([
            "pick_vial_dumping_station.urp",
            "before_shaking_vial.urp",
            lambda: self.shaker.grab_and_shaking(duration_sec=20),
            "after_shaking_vial.urp",
            "place_vial_dumping_station.urp",
        ])

    def dumping(self): 
        self.dummy.run_programs([
            "pick_cru_B.urp",
            "dumping.urp",
            "place_cru_B.urp",
        ])

    def tapping(self):
        self.dummy.run_programs([
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
        ])

    def xrd_powder_dispensing(self) -> Tuple[int, bool]:
        # self.capping("A")
        self.dummy.run_program("pick_vial_dumping_station_reverse.urp")
        self.dummy.run_program("before_weighing_vial.urp")
        time.sleep(3)
        initial_weight = self.balance.get_mass_in_mg()
        self.dummy.run_program("after_weighing_vial.urp")
        current_weight = initial_weight
        last_weight = 0

        trial_time = 0
        while initial_weight - current_weight < 100 and trial_time < 8 and abs(current_weight - last_weight) >= 5:
            trial_time += 1
            self.dummy.run_program("xrd_powder_dispensing.urp")
            self.dummy.run_program("before_weighing_vial.urp")
            time.sleep(3)
            last_weight = current_weight
            current_weight = self.balance.get_mass_in_mg()
            self.dummy.run_program("after_weighing_vial.urp")
        
        self.dummy.run_program("place_vial_dumping_station_reverse.urp")
        # self.decapping("A")

        return initial_weight - current_weight, initial_weight - current_weight >= 100

    def xrd_sample_flattening(self):
        self.dummy.run_programs([
            "horizonal_to_vertical.urp",
            "pick_cap_B.urp",
            "xrd_sample_flattening.urp",
            "place_cap_B.urp",
            "vertical_to_horizonal.urp",
        ])

    def weighing(self) -> int:
        self.dummy.run_programs([
            "pick_cru_B.urp",
            "before_weighing.urp",
        ])
        time.sleep(3)
        mass_in_mg = self.balance.get_mass_in_mg()
        self.dummy.run_programs([
            "after_weighing.urp",
            "place_cru_B.urp",
        ])
        return mass_in_mg


import cv2

cam = cv2.VideoCapture(1)


def take_photo(name):
    ret, frame = cam.read()
    cv2.imwrite(name, frame)



if __name__ == "__main__":
    from pathlib import Path
    from tqdm import tqdm 
    alab = ALab()
    # alab.decapping("B")
    alab.dummy.run_programs([
        "horizonal_to_vertical.urp",
        "pick_transfer_rack_1.auto.script",
        "place_transfer_rack_B.auto.script",
        "pick_vial_rack_B_1.auto.script",
        "place_dumping_station.auto.script",
        "vertical_to_horizonal.urp",
    ])
    # alab.sample_processing()
    alab.xrd_powder_dispensing()
    alab.xrd_sample_flattening()
    # alab.capping(cap="A")
    # alab.decapping(cap="A")
    # alab.xrd_powder_dispensing()

    # for _ in tqdm(range(50)):
        # alab.capping(cap="A")
        # take_photo((Path(__file__).parent / f"vial_5_{_}.jpg").as_posix())
        # alab.decapping(cap="A")
