"""Initialize HA's HTTP/schema aliases before pytest loads third-party plugins."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import homeassistant  # noqa: E402,F401
import pytest  # noqa: E402

raise SystemExit(pytest.main(sys.argv[1:]))
