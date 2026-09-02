"""pytest 根 conftest：保证 apps/server 在 sys.path 上（无需 editable 安装）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
