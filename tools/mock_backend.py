#!/usr/bin/env python3
"""兼容入口：实现已模块化迁移到 tools/backend/ 包。

    python tools/mock_backend.py        # 等价于 mock 渠道启动新后端
    PAY_PROVIDER=wechat python tools/backend/server.py   # 微信支付
    PAY_PROVIDER=alipay python tools/backend/server.py   # 支付宝当面付
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("PAY_PROVIDER", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.server import main  # noqa: E402

if __name__ == "__main__":
    main()
