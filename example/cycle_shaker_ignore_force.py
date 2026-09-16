"""
Same as cycle_shaker.py, but Python never aborts on grip force / Arduino ERROR.

Arduino firmware still stops the jaws when its FSR limit is hit. If that trip
never happens (CLOSE + ERROR, soft force reading), this script still shakes.

Example:
  python example/cycle_shaker_ignore_force.py --duration-min 3 --frequency 45
"""

from __future__ import annotations

import os

os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import signal
import time

from alab_control.shaker_with_motor_controller import ShakerWMC

DEFAULT_IP = "192.168.1.189"
SHAKE_CHUNK_SEC = 10 * 60
REST_SEC = 60
CTRL_C_OPEN_DELAY_SEC = 5


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def cycle_shaker(
    duration_sec: float,
    frequency: float,
    ip_address: str = DEFAULT_IP,
    shake_chunk_sec: float = SHAKE_CHUNK_SEC,
    rest_sec: float = REST_SEC,
    tighten_steps: int = 2,
) -> None:
    if duration_sec <= 0:
        raise ValueError("duration must be positive")
    if frequency <= 0:
        raise ValueError("frequency must be positive")

    shaker = ShakerWMC(ip_address)
    remaining = float(duration_sec)
    chunk_index = 0

    def _on_sigint(signum, frame):
        print("\nCtrl+C: stopping shaker...")
        try:
            shaker.stop()
        except Exception as exc:
            print(f"stop() failed: {exc}")
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGINT, _on_sigint)

    print(
        f"Plan: shake {_format_duration(duration_sec)} at {frequency} Hz "
        f"in chunks of {_format_duration(shake_chunk_sec)} "
        f"with {_format_duration(rest_sec)} rests (rests not counted)."
    )
    print(
        f"Arduino gripper: {ip_address} | Phidget mill via ShakerWMC "
        "| ignore Python grip-force checks"
    )
    state = shaker.get_state()
    print(f"State before: {state}")

    if state.get("system_status") == "ERROR":
        print("Arduino in ERROR; resetting before grip...")
        shaker.reset()
        state = shaker.get_state()
        print(f"State after reset: {state}")

    if state.get("gripper_status") == "CLOSE":
        print(
            f"Gripper already CLOSE (force_reading={state.get('force_reading')}); "
            "skipping close_gripper()."
        )
    else:
        print("Closing gripper (Arduino FSR stop still active; no Python force abort)...")
        shaker.close_gripper(check_force=False)
        print(f"Gripper after close: {shaker.get_state()}")

    print(f"Tightening grip by {tighten_steps} extra step(s) (/more)...")
    print(f"Gripper after tighten: {shaker.tighten_gripper(steps=tighten_steps)}")

    interrupted = False
    try:
        while remaining > 0:
            chunk_index += 1
            this_chunk = min(shake_chunk_sec, remaining)
            print(
                f"\n=== Chunk {chunk_index}: shake {_format_duration(this_chunk)} "
                f"at {frequency} Hz "
                f"({_format_duration(remaining - this_chunk)} left after) ==="
            )
            shaker.shaking(
                duration_sec=this_chunk,
                frequency=frequency,
                ignore_arduino_error=True,
            )
            remaining -= this_chunk

            if remaining > 0:
                print(
                    f"Resting {_format_duration(rest_sec)} before next chunk "
                    f"({_format_duration(remaining)} shake time still owed)..."
                )
                time.sleep(rest_sec)
    except KeyboardInterrupt:
        interrupted = True
        try:
            shaker.stop()
        except Exception as exc:
            print(f"stop() failed: {exc}")
        print(
            f"Waiting {CTRL_C_OPEN_DELAY_SEC} seconds before opening gripper..."
        )
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        time.sleep(CTRL_C_OPEN_DELAY_SEC)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        print("\nOpening gripper...")
        try:
            shaker.open_gripper(check_force=False)
        except Exception as exc:
            print(f"open_gripper failed: {exc}")
            try:
                shaker.stop()
            except Exception:
                pass
            raise
        print(f"Done. State after: {shaker.get_state()}")
        if interrupted:
            print("Stopped early by Ctrl+C.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Close gripper (Arduino FSR still stops the jaws), then shake even "
            "if the FSR trip / Python force check did not pass."
        )
    )
    parser.add_argument(
        "--duration-min",
        type=float,
        required=True,
        help="Total active shake time X in minutes (rests excluded).",
    )
    parser.add_argument(
        "--frequency",
        "-f",
        type=float,
        required=True,
        help="Shake frequency Y in Hz.",
    )
    parser.add_argument(
        "--ip",
        default=DEFAULT_IP,
        help=f"Arduino gripper IP (default {DEFAULT_IP}).",
    )
    parser.add_argument(
        "--chunk-min",
        type=float,
        default=10.0,
        help="Active shake minutes per interval (default 10).",
    )
    parser.add_argument(
        "--rest-min",
        type=float,
        default=1.0,
        help="Rest minutes between intervals (default 1).",
    )
    parser.add_argument(
        "--tighten-steps",
        type=int,
        default=2,
        help="Extra /more retract steps after FSR stop (default 2).",
    )
    args = parser.parse_args()

    cycle_shaker(
        duration_sec=args.duration_min * 60.0,
        frequency=args.frequency,
        ip_address=args.ip,
        shake_chunk_sec=args.chunk_min * 60.0,
        rest_sec=args.rest_min * 60.0,
        tighten_steps=args.tighten_steps,
    )


if __name__ == "__main__":
    main()
