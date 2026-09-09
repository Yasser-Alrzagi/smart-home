"""Desktop client entry point.

Usage (Windows, from the repository root):
    python desktop_client/main.py
    python desktop_client/main.py --api http://127.0.0.1:8000

The API address can also come from the SMART_HOME_API environment variable.
Requires NO third-party packages: tkinter and urllib are part of Python.
"""

from __future__ import annotations

import argparse
import os

from .api import DEFAULT_API, ApiClient
from .app import DesktopApp


def main() -> None:
    parser = argparse.ArgumentParser(description="سكن بازرعة — عميل سطح المكتب")
    parser.add_argument("--api", default=os.environ.get("SMART_HOME_API", DEFAULT_API))
    args = parser.parse_args()
    DesktopApp(ApiClient(args.api)).run()


if __name__ == "__main__":
    main()
