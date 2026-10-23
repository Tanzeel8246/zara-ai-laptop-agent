"""CodeHubb Assistant - remote laptop agent driven from your phone."""

# The version lives in agent/version.py (single source of truth, Phase 5);
# it is re-exported here so `from agent import __version__` keeps working.
from .version import __version__

__all__ = ["__version__"]
