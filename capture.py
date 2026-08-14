"""Utility to create templates.

Takes ONE screenshot of the emulator's current screen and saves it as a PNG,
so you can open the image and crop the task buttons/icons.

Usage:
    python capture.py                      # saves screen.png (default port)
    python capture.py my_screen.png        # custom name
    python capture.py help.png --port 5615  # from a specific emulator

This is the ONLY place in the project that writes an image to disk, and only
when you run it manually. The bot itself (main.py) never saves screenshots.
"""
from __future__ import annotations

import argparse

import cv2

import config
from adb_controller import ADBController


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the emulator screen.")
    parser.add_argument("filename", nargs="?", default="screen.png",
                        help="Output file (default: screen.png)")
    parser.add_argument("--host", default=config.ADB_HOST)
    parser.add_argument("--port", type=int, default=config.ADB_PORT)
    args = parser.parse_args()

    controller = ADBController(host=args.host, port=args.port)
    controller.connect()
    screen = controller.screenshot()
    cv2.imwrite(args.filename, screen)
    h, w = screen.shape[:2]
    print(f"Screenshot saved to '{args.filename}' ({w}x{h}) from {controller.serial}.")
    print("Open the image, crop the buttons and save the PNGs into the templates/ folder.")


if __name__ == "__main__":
    main()
