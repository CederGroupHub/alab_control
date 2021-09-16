import time
import unittest

from alab_control import furnace_epc_3016


class TestFurnace(unittest.TestCase):
    def setUp(self):
        self.furnace = furnace_epc_3016.FurnaceController(address="192.168.111.222")

    def tearDown(self):
        self.furnace.close()  # close the connection

    def test_temperature(self):
        t1 = self.furnace.current_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_temperature

        self.assertAlmostEqual(t1, t2, delta=3., msg="Inconsistent temperature measurement")
