# -*- coding: utf-8 -*-
"""配置与常量（数据层）。

对外接口：
    - SupportConfig：宿主传入的配置数据类 + validate()
    - 模块级常量：DEFAULT_TRIGGERS / NEVER_BUTTON_FIRST_COUNT /
      DEFAULT_NEVER_SKIP_COUNT / FALLBACK_TITLE / FALLBACK_BODY /
      DEFAULT_ICON_PATH / DEFAULT_PROMPTS_PATH / PROJECT_ROOT / MODULE_DIR

依赖模块：无（仅标准库）
被依赖：policy / store / catalog / dialog / core 都从本模块取常量与配置类型
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

MODULE_DIR = Path(__file__).resolve().parent          # support_prompt 包目录
# 包的父目录：源码布局下是 python/；pip 安装后是 site-packages/。
# 仅作为向后兼容的信息常量暴露，打包后路径可能不再指向项目根。
PROJECT_ROOT = MODULE_DIR.parent
DEFAULT_PROMPTS_PATH = MODULE_DIR / "prompts_zh.json"  # 包内自带文案
DEFAULT_ICON_PATH = MODULE_DIR / "coffee_icon.jpg"      # 包内自带图标（随包分发）

# ---------------------------------------------------------------------------
# 触发策略与“不再提醒”阈值
# ---------------------------------------------------------------------------

# 触发序号：前期轻、中期加、后期密但不轰炸；前 3 次只显示“稍后再说”，
# 第 4 次起（直到 hard_stop_count=40）才出现“不再提醒”按钮。
DEFAULT_TRIGGERS = (1, 2, 3, 6, 7, 10, 13, 16, 19, 22, 25, 28, 30, 33, 36, 38, 40)

# “不再提醒”按钮首次出现的成功次数阈值（前 3 次只给“稍后再说”）
NEVER_BUTTON_FIRST_COUNT = 4
# 收款信息（二维码/链接/购买按钮）首次展示的成功次数阈值（前 3 次纯祝福）
PAYMENT_INFO_FIRST_COUNT = 4
# 点击“不再提醒”后跳过多少次成功再恢复提醒
DEFAULT_NEVER_SKIP_COUNT = 5

# ---------------------------------------------------------------------------
# “我已完成支持”自动轮询参数
# ---------------------------------------------------------------------------

# 用户点一次“我已完成支持”后，每隔多久自动重查一次 /support/verify
VERIFY_POLL_INTERVAL_MS = 4000
# 自动轮询最长等待时间（超时后停止，提示用户稍后再点）
VERIFY_POLL_TIMEOUT_MS = 10 * 60 * 1000

# ---------------------------------------------------------------------------
# 兜底文案
# ---------------------------------------------------------------------------

FALLBACK_TITLE = "可以请我喝杯咖啡吗？"
FALLBACK_BODY = (
    "第 {n} 次处理成功！感谢你的信任。可以请我喝杯咖啡支持一下吗？"
    "只买一次就好——以后不会再用这件事打扰你。"
)


@dataclass
class SupportConfig:
    app_id: str = ""
    api_base_url: str = ""                    # 空 = 离线模式（不自动确认赞助）
    contact_email: str = ""                   # 必填
    contact_email_subject: str = "关于使用体验的反馈"
    checkout_url: str = ""                    # 兜底支持链接
    qr_image_url: str = ""                    # 网络二维码（优先）
    qr_image_local: str = ""                  # 本地二维码（兜底）
    icon_path: str = ""                       # 窗口/标题图标（空则用内置咖啡杯）
    trigger_indices: tuple = DEFAULT_TRIGGERS
    hard_stop_count: int = 40
    allow_never_remind: bool = True
    never_remind_skip_count: int = DEFAULT_NEVER_SKIP_COUNT  # 点“不再提醒”后跳过的成功次数
    prompts_file: str = ""                    # 空 = 使用模块自带 prompts_zh.json
    http_timeout_ms: int = 8000
    settings_org: str = "SupportPrompt"
    settings_app: str = ""                    # 空 = app_id
    settings_group: str = "SupportPrompt"
    debug_logging: bool = False

    def validate(self) -> Optional[str]:
        if not self.app_id.strip():
            return "app_id 不能为空"
        if not self.contact_email.strip():
            return "contact_email 不能为空"
        if self.hard_stop_count <= 0:
            return "hard_stop_count 必须大于 0"
        if self.never_remind_skip_count < 0:
            return "never_remind_skip_count 不能为负数"
        if self.api_base_url and not self.api_base_url.startswith(("http://", "https://")):
            return "api_base_url 必须是 http/https 地址"
        return None
