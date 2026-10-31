"""PyInstaller runtime hook: keep debug runtime artifacts under debug/."""
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.executable).resolve().parent.parent
temporary = root / 'tmp'
temporary.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
tempfile.tempdir = str(temporary)
os.environ['BATTERY_VIEWER_DEBUG'] = '1'
logs = root / 'logs'
logs.mkdir(exist_ok=True)
sys.stdout = open(logs / 'runtime.log', 'a', encoding='utf-8', buffering=1)
sys.stderr = sys.stdout
