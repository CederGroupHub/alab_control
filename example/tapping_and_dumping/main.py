import time
from concurrent.futures import ThreadPoolExecutor

import flask

from alab_control.ball_dispenser import BallDispenser
from alab_control.cap_dispenser import CapDispenser
from alab_control.robot_arm_ur5e.robots import Dummy
from alab_control.shaker import Shaker


class Tasks:
    def __init__(self):
        self.dummy = Dummy(ip="192.168.0.23")
        self.cap_dispenser = CapDispenser(ip_address="192.168.0.31")
        self.shaker = Shaker(ip_address="192.168.0.32")
        self.ball_dispenser = BallDispenser(ip_address="192.168.0.33")

    def sample_processing(self):
        self.dumping()
        self.tapping()

    def dumping(self):
        self.dummy._dashboard_client.run_program("pick_cru_B.urp")
        self.dummy._dashboard_client.run_program("dumping.urp")
        self.dummy._dashboard_client.run_program("place_cru_B.urp")

    def tapping(self):
        self.dummy._dashboard_client.run_program("pick_vial_dumping_station.urp")
        self.dummy._dashboard_client.run_program("place_vial_tapping_station.urp")

        self.dummy._dashboard_client.run_program("pick_cru_B.urp")
        self.dummy._dashboard_client.run_program("before_tapping.urp")
        if self.shaker.is_running():
            time.sleep(15)
        else:
            self.shaker.shaking(duration_sec=15)
        self.dummy._dashboard_client.run_program("after_tapping.urp")
        self.dummy._dashboard_client.run_program("place_cru_B.urp")

        self.dummy._dashboard_client.run_program("pick_vial_tapping_station.urp")
        self.dummy._dashboard_client.run_program("place_vial_dumping_station.urp")


class App:
    def __init__(self):
        self.tasks = Tasks()
        self.app = flask.Flask(__name__)
        self.sample_processing_thread = ThreadPoolExecutor(max_workers=1)
        self.shaking_thread = ThreadPoolExecutor(max_workers=1)
        self.ball_dispenser_thread = ThreadPoolExecutor(max_workers=1)
        self.cap_dispenser_thread = ThreadPoolExecutor(max_workers=1)

        @self.app.route("/", methods=["GET"])
        def index():
            return flask.send_file("index.html")

        @self.app.route("/sample_processing")
        def sample_processing():
            if self.sample_processing_thread._work_queue.qsize() > 0:
                return {"status": "busy"}
            self.sample_processing_thread.submit(self.tasks.sample_processing)
            return {"status": "ok"}

        @self.app.route("/shaking")
        def shaking():
            if self.shaking_thread._work_queue.qsize() > 0:
                return {"status": "busy"}
            duration_sec = flask.request.args.get("duration_sec", default=120, type=int)
            self.shaking_thread.submit(self.tasks.shaker.shaking, duration_sec=duration_sec)
            return {"status": "ok"}

        @self.app.route("/dispensing_balls")
        def dispensing_balls():
            if self.ball_dispenser_thread._work_queue.qsize() > 0:
                return {"status": "busy"}
            self.ball_dispenser_thread.submit(self.tasks.ball_dispenser.dispense_balls)
            return {"status": "ok"}

        @self.app.route("/cap_dispenser")
        def cap_dispenser():
            if self.cap_dispenser_thread._work_queue.qsize() > 0:
                return {"status": "busy"}
            n = flask.request.args.get("n", type=int)
            if self.tasks.cap_dispenser.is_open[n - 1]:
                self.cap_dispenser_thread.submit(self.tasks.cap_dispenser.close, n=n)
            else:
                self.cap_dispenser_thread.submit(self.tasks.cap_dispenser.open, n=n)
            return {"status": "ok"}

        @self.app.route("/grab")
        def grab():
            if self.shaking_thread._work_queue.qsize() > 0:
                return {"status": "busy"}
            if self.tasks.shaker.get_state().is_grabber_closed():
                self.shaking_thread.submit(self.tasks.shaker.release)
            else:
                self.shaking_thread.submit(self.tasks.shaker.grab)
            return {"status": "ok"}

        @self.app.route("/status")
        def status():
            return {
                "shaker": self.tasks.shaker.get_state().name,
                "robot": "RUNNING" if self.tasks.dummy.is_running() else "STOPPED",
                "ball_dispenser": self.tasks.ball_dispenser.get_state().name,
                "cap_dispenser": [is_open and "OPEN" or "CLOSED"
                                  for is_open in self.tasks.cap_dispenser.is_open],
            }

    def run(self):
        self.app.run(host="127.0.0.1", port=4999)


if __name__ == '__main__':
    app = App()
    app.run()
    ...
