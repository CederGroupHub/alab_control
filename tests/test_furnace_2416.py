import time
import unittest
from datetime import timedelta
from typing import List

from pytest_reraise import Reraise

from alab_control import furnace_2416
from alab_control.furnace_2416.furnace_driver import SegmentType, ProgramEndType, TimeUnit


class TestFurnace(unittest.TestCase):
    def setUp(self):
        self.furnace = furnace_2416.FurnaceController(port="COM5", timeout=1)
        self.furnace.stop()

    def tearDown(self):
        self.furnace.stop()
        self.furnace.close()  # close the connection

    def test_temperature(self):
        t1 = self.furnace.current_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_temperature
        self.assertAlmostEqual(t1, t2, delta=1., msg="Inconsistent temperature measurement")

    def test_target_temperature(self):
        t1 = self.furnace.current_target_temperature
        time.sleep(0.1)
        t2 = self.furnace.current_target_temperature

        self.assertAlmostEqual(t1, t2, delta=2., msg="Inconsistent target temperature measurement")

    def test_reset(self):
        self.furnace.stop()
        self.assertEqual(self.furnace.program_mode.value, 1, msg="Reset fails.")

    def test_config_segment(self):
        if self.furnace["Programmer.Program_01.dwLU"] != TimeUnit.MINUTE.value:
            self.furnace["Programmer.Program_01.dwLU"] = TimeUnit.MINUTE.value
        if self.furnace["Programmer.Program_01.rmPU"] != TimeUnit.MINUTE.value:
            self.furnace["Programmer.Program_01.rmPU"] = TimeUnit.MINUTE.value

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

        seg_3 = dict(segment_type=SegmentType.DWELL, duration=timedelta(hours=16))
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


class TestMultipleFurnaces(unittest.TestCase):
    def setUp(self) -> None:
        self.furnaces: List[furnace_2416.FurnaceController] = \
            [furnace_2416.FurnaceController(port=f"COM{port}", timeout=1)
             for port in range(6, 10)]

        for furnace in self.furnaces:
            furnace.stop()

    def tearDown(self) -> None:
        for furnace in self.furnaces:
            furnace.stop()
            furnace.close()

    def test_temperatures(self):
        for furnace in self.furnaces:
            t1 = furnace.current_temperature
            time.sleep(0.1)
            t2 = furnace.current_temperature
            self.assertAlmostEqual(t1, t2, delta=.2, msg="Inconsistent temperature measurement")

    def test_target_temperatures(self):
        for furnace in self.furnaces:
            t1 = furnace.current_target_temperature
            time.sleep(0.1)
            t2 = furnace.current_target_temperature

            self.assertAlmostEqual(t1, t2, delta=2., msg="Inconsistent target temperature measurement")

    def test_reset(self):
        for furnace in self.furnaces:
            furnace.stop()
            self.assertEqual(furnace.program_mode.value, 1, msg="Reset fails.")

    def test_set_program(self):
        import threading

        reraise = Reraise()

        @reraise.wrap
        def set_program(furnace):
            if furnace["Programmer.Program_01.dwLU"] != TimeUnit.MINUTE.value:
                furnace["Programmer.Program_01.dwLU"] = TimeUnit.MINUTE.value
            if furnace["Programmer.Program_01.rmPU"] != TimeUnit.MINUTE.value:
                furnace["Programmer.Program_01.rmPU"] = TimeUnit.MINUTE.value

            seg_1 = dict(segment_type=SegmentType.RAMP_TIME, target_setpoint=20,
                         duration=timedelta(seconds=60))
            furnace._configure_segment_i(i=1, **seg_1)
            read_1 = furnace._read_segment_i(i=1)
            self.assertDictEqual(read_1, {**read_1, **seg_1},
                                 msg="RAMP_TIME segment type: inconsistent read and write")

            seg_2 = dict(segment_type=SegmentType.RAMP_RATE, target_setpoint=40,
                         ramp_rate_per_min=10)
            furnace._configure_segment_i(i=2, **seg_2)
            read_2 = furnace._read_segment_i(i=2)
            self.assertDictEqual(read_2, {**read_2, **seg_2},
                                 msg="RAMP_RATE segment type: inconsistent read and write")

            seg_3 = dict(segment_type=SegmentType.DWELL, duration=timedelta(hours=16))
            furnace._configure_segment_i(i=3, **seg_3)
            read_3 = furnace._read_segment_i(i=3)
            self.assertDictEqual(read_3, {**read_3, **seg_3},
                                 msg="DWELL segment type: inconsistent read and write")

            seg_4 = dict(segment_type=SegmentType.STEP, target_setpoint=0)
            furnace._configure_segment_i(i=4, **seg_4)
            read_4 = furnace._read_segment_i(i=4)
            self.assertDictEqual(read_4, {**read_4, **seg_4},
                                 msg="STEP segment type: inconsistent read and write")

            seg_5 = dict(segment_type=SegmentType.END, endt=ProgramEndType.STOP)
            furnace._configure_segment_i(i=5, **seg_5)
            read_5 = furnace._read_segment_i(i=5)
            self.assertDictEqual(read_5, {**read_5, **seg_5},
                                 msg="END segment type: inconsistent read and write")

        threads = []
        for furnace in self.furnaces:
            t = threading.Thread(target=set_program, args=(furnace,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        reraise()

    def test_run(self):
        import threading

        self.test_set_program()
        reraise = Reraise()

        @reraise.wrap
        def run_furnace(i):
            self.furnaces[i].play()
            time.sleep(5)
            self.assertEqual(self.furnaces[i].program_mode.value, 2, msg="Run fails.")
            self.furnaces[i].stop()

        threads = []
        for i in range(len(self.furnaces)):
            t = threading.Thread(target=run_furnace, args=(i,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        reraise()