import time
import unittest
from datetime import timedelta

from alab_control import furnace_2416
from alab_control.furnace_2416.furnace_driver import SegmentType, ProgramEndType


class TestFurnace(unittest.TestCase):
    def setUp(self):
        self.furnace = furnace_2416.FurnaceController(port="COM3", timeout=1)
        self.furnace.stop()

    def tearDown(self):
        self.furnace.stop()
        self.furnace.close()  # close the connection

    def test_temperature(self):
        t1 = self.furnace.current_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_temperature
        print(t1)
        self.assertAlmostEqual(t1, t2, delta=.2, msg="Inconsistent temperature measurement")

    def test_target_temperature(self):
        t1 = self.furnace.current_target_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_target_temperature

        self.assertAlmostEqual(t1, t2, delta=2., msg="Inconsistent target temperature measurement")

    def test_reset(self):
        self.furnace.stop()
        self.assertEqual(self.furnace.program_mode.value, 1, msg="Reset fails.")

    def test_config_segment(self):
        seg_1 = dict(segment_type=SegmentType.RAMP_TIME, target_setpoint=20,
                     duration=timedelta(seconds=60))
        self.furnace._configure_segment_i(i=1, **seg_1)
        read_1 = self.furnace._read_segment_i(i=1)
        self.assertDictEqual(read_1, {**read_1, **seg_1},
                             msg="RAMP_TIME segment type: inconsistent read and write")

        seg_2 = dict(segment_type=SegmentType.RAMP_RATE, target_setpoint=40,
                     ramp_rate_per_min=10)
        self.furnace._configure_segment_i(i=2, **seg_2)
        read_2 = self.furnace._read_segment_i(i=2)
        self.assertDictEqual(read_2, {**read_2, **seg_2},
                             msg="RAMP_RATE segment type: inconsistent read and write")

        seg_3 = dict(segment_type=SegmentType.DWELL, duration=timedelta(hours=12))
        self.furnace._configure_segment_i(i=3, **seg_3)
        read_3 = self.furnace._read_segment_i(i=3)
        self.assertDictEqual(read_3, {**read_3, **seg_3},
                             msg="DWELL segment type: inconsistent read and write")

        seg_4 = dict(segment_type=SegmentType.STEP, target_setpoint=0)
        self.furnace._configure_segment_i(i=4, **seg_4)
        read_4 = self.furnace._read_segment_i(i=4)
        self.assertDictEqual(read_4, {**read_4, **seg_4},
                             msg="STEP segment type: inconsistent read and write")

        seg_5 = dict(segment_type=SegmentType.END, endt=ProgramEndType.STOP)
        self.furnace._configure_segment_i(i=5, **seg_5)
        read_5 = self.furnace._read_segment_i(i=5)
        self.assertDictEqual(read_5, {**read_5, **seg_5},
                             msg="END segment type: inconsistent read and write")

    def test_run(self):
        self.test_config_segment()
        self.furnace.play()
        time.sleep(5)
        self.assertEqual(self.furnace.program_mode.value, 2, msg="Run fails.")
        self.furnace.stop()
