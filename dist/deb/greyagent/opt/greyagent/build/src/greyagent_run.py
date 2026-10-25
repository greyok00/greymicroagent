import sys
from pathlib import Path

ROOT = Path("/home/grey/greyagent")
sys.path.insert(0, str(ROOT))

from ui.app import main

main()
