"""Stop the DASH mill (Phidget), wait 5 seconds, then open the gripper."""

from __future__ import annotations

import os

# Disable Intel Fortran Ctrl+C abort (pulled in via NumPy/SciPy). Must be first.
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import time

from alab_control.shaker_with_motor_controller import ShakerWMC

DEFAULT_IP = "192.168.1.189"
OPEN_DELAY_SEC = 5


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stop shaking, wait 5 s, then open the gripper."
    )
    parser.add_argument(
        "--ip",
        default=DEFAULT_IP,
        help=f"Arduino gripper IP (default {DEFAULT_IP}).",
    )
    parser.add_argument(
        "--delay-sec",
        type=float,
        default=OPEN_DELAY_SEC,
        help=f"Seconds to wait after stop before opening (default {OPEN_DELAY_SEC}).",
    )
    args = parser.parse_args()

    shaker = ShakerWMC(args.ip)
    print(f"State before: {shaker.get_state()}")
    print("Stopping mill...")
    shaker.stop()
    print(f"Waiting {args.delay_sec:g} seconds before opening gripper...")
    time.sleep(args.delay_sec)
    print("Opening gripper...")
    shaker.open_gripper()
    print(f"Done. State after: {shaker.get_state()}")


if __name__ == "__main__":
    main()
