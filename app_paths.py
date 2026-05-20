"""Resolve paths for script mode and PyInstaller executable mode."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()


def app_path(*parts: str) -> Path:
    return APP_DIR.joinpath(*parts)


def setup_runtime() -> None:
    """Chromium + working directory next to the program folder."""
    os.chdir(APP_DIR)
    browsers = app_path("browsers")
    if browsers.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def resolve_data_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    return app_path(path_str)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)
