"""Sound Overlay root package."""

import sys

if sys.platform == "win32" and not hasattr(sys, "coinit_flags"):
    sys.coinit_flags = 2  # COINIT_APARTMENTTHREADED for compatibility with Qt OleInitialize
