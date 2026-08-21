"""
Close the DASH shaker gripper, shake in 10-minute bursts with 1-minute rests,
then open the gripper.

Total active shake time is X (rests do not count toward X). Frequency is Y.

Example:
  python example/cycle_shaker.py --duration-min 30 --frequency 25
  -> close, shake 10, rest 1, shake 10, rest 1, shake 10, open

Ctrl+C: stop mill, wait 5 s, open gripper.
Must set FOR_DISABLE_CONSOLE_CTRL_HANDLER before NumPy/SciPy load, otherwise
Intel Fortran aborts the process on Ctrl+C (forrtl error 200).
"""

from __future__ import annotations

import os

# Disable Intel Fortran Ctrl+C abort (pulled in via NumPy/SciPy). Must be first.
os.environ["FOR_DISABLE_CONSOLE_CTRL_HANDLER"] = "1"

import argparse
import signal
import time

from alab_control.shaker_with_motor_controller import ShakerWMC

DEFAULT_IP = "192.168.1.189"
SHAKE_CHUNK_SEC = 10 * 60  # 10 minutes of shaking per interval
REST_SEC = 60  # 1 minute pause between intervals
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
) -> None:
    if duration_sec <= 0:
        raise ValueError("duration must be positive")
    if frequency <= 0:
        raise ValueError("frequency must be positive")

    shaker = ShakerWMC(ip_address)
    remaining = float(duration_sec)
    chunk_index = 0

    def _on_sigint(signum, frame):
        # Ask the Phidget profile thread to stop, then let KeyboardInterrupt unwind.
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
    print(f"Arduino gripper: {ip_address} | Phidget mill via ShakerWMC")
    state = shaker.get_state()
    print(f"State before: {state}")

    if state.get("gripper_status") == "CLOSE":
        print("Gripper already CLOSE; skipping close_gripper().")
    else:
        print("Closing gripper...")
        shaker.close_gripper()
        print(f"Gripper closed: {shaker.get_state()}")

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
            shaker.shaking(duration_sec=this_chunk, frequency=frequency)
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
        # Ignore further Ctrl+C during the delay so cleanup can finish.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        time.sleep(CTRL_C_OPEN_DELAY_SEC)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        print("\nOpening gripper...")
        try:
            shaker.open_gripper()
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
            "Close gripper, shake total time X at frequency Y in 10-minute "
            "intervals with 1-minute rests, then open gripper."
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
    args = parser.parse_args()

    cycle_shaker(
        duration_sec=args.duration_min * 60.0,
        frequency=args.frequency,
        ip_address=args.ip,
        shake_chunk_sec=args.chunk_min * 60.0,
        rest_sec=args.rest_min * 60.0,
    )


if __name__ == "__main__":
    main()
