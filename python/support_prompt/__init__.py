# -*- coding: utf-8 -*-
"""处理成功后评价/赞助弹窗模块（Python / PySide6 版）。

与 C++ 版 SupportPrompt 完全独立，但保持同一套语义与后端契约：
  - 触发序号默认 1,2,3,6,7,10,13,16,19,22,25,28,30；第 30 次后不再提示
  - 后端校验（方案 C）：去买咖啡 -> POST /support/session/create；
    我已完成支持 -> GET /support/verify?sid=...；verified=true 则永久关闭
  - 文案 JSON 每条都包含“只买一次，以后不再出现提示”的含义
  - suppressed 是“是否继续提示”的唯一真值（QSettings 持久化）

点击“去买咖啡”后会打开支付页面；微信和支付宝二维码只在支付页面展示。

宿主用法：
    from support_prompt import SupportPrompt, SupportConfig

    cfg = SupportConfig(
        app_id="my-app",
        api_base_url="https://api.example.com",   # 留空 = 离线模式
        contact_email="you@example.com",
        checkout_url="https://www.buymeacoffee.com/lujieaa",
    )
    prompt = SupportPrompt(cfg, parent=main_window)
    prompt.on_process_success()  # 每次业务处理成功后调用

模块分层：
    config   常量与 SupportConfig（数据层，无依赖）
    policy   PromptPolicy 触发策略（纯逻辑，可单测）
    store    LocalStore 本地持久化（数据层）
    catalog  PromptCatalog 文案目录（数据层）
    dialog   SupportPromptDialog 弹窗 UI（渲染层）
    core     SupportPrompt 编排（控制层，串联以上全部）
"""

from .catalog import PromptCatalog
from .config import (
    DEFAULT_ICON_PATH,
    DEFAULT_NEVER_SKIP_COUNT,
    DEFAULT_PROMPTS_PATH,
    DEFAULT_TRIGGERS,
    FALLBACK_BODY,
    FALLBACK_TITLE,
    NEVER_BUTTON_FIRST_COUNT,
    PAYMENT_INFO_FIRST_COUNT,
    PROJECT_ROOT,
    SupportConfig,
)
from .core import SupportPrompt
from .dialog import SupportPromptDialog, ThankYouDialog
from .policy import PromptPolicy
from .store import LocalStore

__all__ = [
    "SupportConfig",
    "SupportPrompt",
    "SupportPromptDialog",
    "ThankYouDialog",
    "PromptPolicy",
    "PromptCatalog",
    "LocalStore",
    "DEFAULT_TRIGGERS",
    "NEVER_BUTTON_FIRST_COUNT",
    "PAYMENT_INFO_FIRST_COUNT",
    "DEFAULT_NEVER_SKIP_COUNT",
    "DEFAULT_ICON_PATH",
    "DEFAULT_PROMPTS_PATH",
    "FALLBACK_TITLE",
    "FALLBACK_BODY",
    "PROJECT_ROOT",
]
