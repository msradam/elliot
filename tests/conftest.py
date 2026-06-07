"""Test fixtures: force offline + headless before any elliot import.

``elliot.config.CONFIG`` reads the environment once at import, so these have to
be set before the package is imported. pytest loads conftest first, so this is
the right place.
"""

import os

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ["ELLIOT_OFFLINE"] = "1"
os.environ["ELLIOT_TICK_DELAY"] = "0"
os.environ.setdefault("ELLIOT_MAX_TICKS", "260")
