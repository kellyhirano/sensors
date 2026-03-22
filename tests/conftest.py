import sys
import os
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock hardware/network dependencies and stdlib modules that cause side effects at import
sys.modules['fcntl'] = MagicMock()   # prevents lock file acquisition at import time
sys.modules['aqi'] = MagicMock()     # python-aqi library, not available outside Pi venv
sys.modules['paho'] = MagicMock()
sys.modules['paho.mqtt'] = MagicMock()
sys.modules['paho.mqtt.publish'] = MagicMock()
