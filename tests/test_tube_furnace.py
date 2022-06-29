import time
from unittest import TestCase

from tube_furnace_mti.tube_furnace import TubeFurnace, FlangeError


class TestTubeFurnace(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tube_furnace = TubeFurnace(furnace_index=2)

    def test_opening(self):
        self.assertTrue(self.tube_furnace.open_door())
        self.assertTrue(self.tube_furnace.close_door())

    def test_closing_timeout(self):
        self.assertTrue(self.tube_furnace.open_door())
        with self.assertRaises(FlangeError):
            self.tube_furnace.close_door(timeout=1)
        self.assertTrue(self.tube_furnace.close_door())

    def test_pause(self):
        self.assertTrue(self.tube_furnace.pause_door())

    def test_opening_safety_temperature(self):
        self.assertFalse(self.tube_furnace.open_door(safety_open_temperature=0))

    def test_opening_safety_pressure(self):
        self.assertFalse(self.tube_furnace.open_door(pressure_min=0, pressure_max=1))

    def test_write_program(self):
        test_profile = {
            "C01": 0,
            "T01": 1,
            "C02": 30,
            "T02": 2,
            "C03": 30,
            "T04": -121,
        }
        self.tube_furnace.write_heating_profile(test_profile)
        profile = self.tube_furnace.read_heating_profile()
        self.assertEqual(profile, {**profile, **test_profile})

    def test_run_program(self):
        test_profile = {
            "C01": 0,
            "T01": 1,
            "C02": 30,
            "T02": 2,
            "C03": 30,
            "T04": -121,
        }
        self.tube_furnace.write_heating_profile(test_profile)
        self.tube_furnace.start_program()
        while self.tube_furnace.autostate != -1:
            time.sleep(4)
        self.tube_furnace.open_door()
        self.tube_furnace.close_door()
