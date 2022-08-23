from pathlib import Path

from flask import Flask
from flask_classful import FlaskView, route
from gevent.pywsgi import WSGIServer
from threading import Thread
from flask_cors import CORS
from alab_control.furnace_2416.furnace_driver import (
    FurnaceController,
    Segment,
    SegmentType,
)

BOX_FURNACE_KEY = {
    "box_b": "COM3",
    "box_c": "COM4",
}  # TODO auto get COM port from hwid etc


class BoxFurnaces:
    def __init__(self):
        # connect to box furnaces
        self.furnaces = self.connect_to_box_furnaces(BOX_FURNACE_KEY)

    # def connect_to_box_furnaces(self, name_to_comport: dict):
    #     furnaces = {}
    #     for furnace_name, comport in name_to_comport.items():
    #         try:
    #             furnaces[furnace_name] = FurnaceController(port=comport)
    #             print(f"Connected to {furnace_name} at port {comport}")
    #         except:
    #             print(f"Failed to connect to {furnace_name} at port {comport}!")
    #     if len(furnaces) == 0:
    #         raise Exception("Could not connect to any box furnaces.")
    #     return furnaces

    def connect_to_box_furnaces(self, name_to_comport: dict):
        furnaces = BOX_FURNACE_KEY
        return furnaces

    def get_furnace(self, name: str) -> FurnaceController:
        if name not in self.furnaces:
            raise ValueError(
                f'Box furnace host is not connected to a furnace by the name of "{name}"!'
            )


class BoxFurnaceServer(FlaskView):
    route_base = "/"

    def __init__(self):
        self.furnaces = BoxFurnaces()

    @route("/available_furnaces", methods=["GET"])
    def get_available_furnaces(self):
        return {"available_furnaces": list(self.furnaces.furnaces.keys())}

    @route("/<furnace_name>/status", methods=["GET"])
    def get_furnace_status(self, furnace_name: str):
        furnace = self.furnaces.get_furnace(name=furnace_name)

        return {
            "is_running": furnace.is_running(),
            "current_temperature": furnace.current_temperature,
            "current_target_temperature": furnace.current_target_temperature,
            "program_mode": furnace.program_mode,
        }

    @route("/<furnace_name>/run_program", methods=["POST"])
    def run_program(self, furnace_name: str):
        data = request.get_json(force=True)  # type: ignore
        if "segments" not in data:
            return {
                "status": "error",
                "errors": "no segments field included in POST request!",
            }, 400

        furnace = self.furnaces.get_furnace(name=furnace_name)

        segments = []
        for segment_kwargs in data["segments"]:
            type = segment_kwargs.pop("segment_type")
            try:
                segments.append(
                    Segment(segment_type=SegmentType(type), **segment_kwargs)
                )
            except:
                raise ValueError(
                    f"Segment of type {type} could not be created with kwargs {segment_kwargs}"
                )

        furnace.run_program(segments)
        return {"status": "success", "furnace": furnace_name}

    @route("/<furnace_name>/stop", methods=["POST"]):
    def stop_furnace(self, furnace_name:str):
        furnace = self.furnaces.get_furnace(name=furnace_name)
        furnace.stop()


    @route("/<furnace_name>/hold", methods=["POST"]):
    def hold_furnace(self, furnace_name:str):
        furnace = self.furnaces.get_furnace(name=furnace_name)
        furnace.hold_program()

    @route("/<furnace_name>/resume", methods=["POST"]):
    def resume_furnace(self, furnace_name:str):
        furnace = self.furnaces.get_furnace(name=furnace_name)
        furnace.resume()

if __name__ == "__main__":
    app = Flask(__name__)
    BoxFurnaceServer.register(app)
    app.run(host="0.0.0.0", port="6678")
