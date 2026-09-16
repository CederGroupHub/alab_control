"""
Poll for the DASH Phidget mill (and optionally the Arduino gripper).
Prints and plays a Windows beep/toast when a device that was offline comes online.

Example:
  python example/watch_phidget.py
  python example/watch_phidget.py --also-arduino --interval 2
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request

from Phidget22.Devices.DCMotor import DCMotor
from Phidget22.Devices.Manager import Manager

DEFAULT_SERIAL = 662113
DEFAULT_ARDUINO_IP = "192.168.1.189"


def _notify(title: str, message: str) -> None:
    print(f"\n*** {title}: {message} ***\n", flush=True)
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        winsound.Beep(880, 200)
        winsound.Beep(1175, 300)
    except Exception:
        pass
    try:
        # Native toast via PowerShell (no extra deps).
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
            "ContentType = WindowsRuntime] > $null; "
            f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$xml.GetElementsByTagName('text').Item(0).AppendChild($xml.CreateTextNode('{title}')) | Out-Null; "
            f"$xml.GetElementsByTagName('text').Item(1).AppendChild($xml.CreateTextNode('{message}')) | Out-Null; "
            f"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PhidgetWatch').Show($toast)"
        )
        import subprocess

        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


def phidget_online(serial: int, timeout_ms: int = 1500) -> bool:
    """Return True if DCMotor channel for serial attaches quickly."""
    motor = DCMotor()
    try:
        motor.setDeviceSerialNumber(serial)
        motor.openWaitForAttachment(timeout_ms)
        motor.close()
        return True
    except Exception:
        try:
            motor.close()
        except Exception:
            pass
        return False


def any_phidget_present(listen_sec: float = 1.5) -> bool:
    seen = []

    def on_attach(_mgr, channel):
        try:
            seen.append(channel.getDeviceSerialNumber())
        except Exception:
            seen.append(-1)

    mgr = Manager()
    try:
        mgr.setOnAttachHandler(on_attach)
        mgr.open()
        time.sleep(listen_sec)
    finally:
        try:
            mgr.close()
        except Exception:
            pass
    return len(seen) > 0


def arduino_online(ip: str, timeout_sec: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://{ip}/state", timeout=timeout_sec) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch for Phidget (and optional Arduino) coming online."
    )
    parser.add_argument(
        "--serial",
        type=int,
        default=DEFAULT_SERIAL,
        help=f"Phidget serial (default {DEFAULT_SERIAL}).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between checks (default 3).",
    )
    parser.add_argument(
        "--also-arduino",
        action="store_true",
        help=f"Also watch Arduino gripper at --arduino-ip.",
    )
    parser.add_argument(
        "--arduino-ip",
        default=DEFAULT_ARDUINO_IP,
        help=f"Arduino IP (default {DEFAULT_ARDUINO_IP}).",
    )
    parser.add_argument(
        "--once-and-exit",
        action="store_true",
        help="Exit after the first online notification for each watched target.",
    )
    args = parser.parse_args()

    phidget_was_up = phidget_online(args.serial)
    arduino_was_up = arduino_online(args.arduino_ip) if args.also_arduino else None

    print(
        f"Watching Phidget serial {args.serial} "
        f"(currently {'ONLINE' if phidget_was_up else 'OFFLINE'})",
        flush=True,
    )
    if args.also_arduino:
        print(
            f"Watching Arduino {args.arduino_ip} "
            f"(currently {'ONLINE' if arduino_was_up else 'OFFLINE'})",
            flush=True,
        )
    print(f"Polling every {args.interval}s. Ctrl+C to stop.\n", flush=True)

    if phidget_was_up:
        _notify("Phidget already online", f"serial {args.serial}")
    if args.also_arduino and arduino_was_up:
        _notify("Arduino already online", args.arduino_ip)

    phidget_done = bool(phidget_was_up and args.once_and_exit)
    arduino_done = (not args.also_arduino) or bool(
        arduino_was_up and args.once_and_exit
    )
    if phidget_done and arduino_done:
        return

    try:
        while not (phidget_done and arduino_done):
            time.sleep(args.interval)

            up = phidget_online(args.serial)
            if up and not phidget_was_up:
                any_note = ""
                if not any_phidget_present(1.0):
                    any_note = " (attach OK)"
                _notify("Phidget ONLINE", f"serial {args.serial}{any_note}")
                if args.once_and_exit:
                    phidget_done = True
            elif not up and phidget_was_up:
                print(f"[{time.strftime('%H:%M:%S')}] Phidget went OFFLINE", flush=True)
            phidget_was_up = up

            if args.also_arduino:
                a_up = arduino_online(args.arduino_ip)
                if a_up and not arduino_was_up:
                    _notify("Arduino ONLINE", args.arduino_ip)
                    if args.once_and_exit:
                        arduino_done = True
                elif not a_up and arduino_was_up:
                    print(
                        f"[{time.strftime('%H:%M:%S')}] Arduino went OFFLINE",
                        flush=True,
                    )
                arduino_was_up = a_up

            status = "Phidget UP" if phidget_was_up else "Phidget DOWN"
            if args.also_arduino:
                status += " | Arduino UP" if arduino_was_up else " | Arduino DOWN"
            print(f"[{time.strftime('%H:%M:%S')}] {status}", flush=True)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
