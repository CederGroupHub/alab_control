import time
import unittest
from datetime import timedelta

from alab_control import furnace_epc_3016
from alab_control.furnace_epc_3016.furnace_driver import SegmentType


class TestFurnace(unittest.TestCase):
    def setUp(self):
        self.furnace = furnace_epc_3016.FurnaceController(address="192.168.111.222")

    def tearDown(self):
        self.furnace.close()  # close the connection

    def test_temperature(self):
        t1 = self.furnace.current_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_temperature

        self.assertAlmostEqual(t1, t2, delta=2., msg="Inconsistent temperature measurement")

    def test_reset(self):
        self.furnace.reset_program()
        self.assertEqual(self.furnace.program_mode.value, 1, msg="Reset fails.")

    def test_config_segment(self):
        self.furnace._configure_segment_i(i=1, segment_type=SegmentType.RAMP_TIME, target_setpoint=20,
                                          time_to_target=timedelta(seconds=3600))
        self.furnace._configure_segment_i(i=2, segment_type=SegmentType.RAMP_RATE, target_setpoint=30,
                                          ramp_rate_per_sec=0.1)
        self.furnace._configure_segment_i(i=3, segment_type=SegmentType.DWELL, duration=timedelta(hours=4))
        self.furnace._configure_segment_i(i=4, segment_type=SegmentType.STEP, target_setpoint=0)
        self.furnace._configure_segment_i(i=5, segment_type=SegmentType.END)
