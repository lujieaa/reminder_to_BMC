# -*- coding: utf-8 -*-
"""触发策略（纯逻辑层，可单测）。

对外接口：
    - PromptPolicy：根据 success_count / suppressed / suppress_until_count
      决定是否弹窗（NONE / SHOW / LAST_SHOW）

依赖模块：config.DEFAULT_TRIGGERS
被依赖：core.SupportPrompt
"""

from __future__ import annotations

from .config import DEFAULT_TRIGGERS


class PromptPolicy:
    """触发策略（与 C++ 版行为一致，纯 Python，可单测）。

    suppress 有两种来源：
      - 永久 suppressed=True：赞助已验证（verified），永不提示。
      - 临时 suppress_until_count>0：用户点了“不再提醒”，
        在 success_count 达到该值之前都不提示，之后恢复。
    """

    NONE, SHOW, LAST_SHOW = 0, 1, 2

    def __init__(self, triggers=DEFAULT_TRIGGERS, hard_stop_count: int = 40):
        self.triggers = sorted(set(t for t in triggers if t > 0)) or list(DEFAULT_TRIGGERS)
        self.hard_stop_count = hard_stop_count if hard_stop_count > 0 else 40

    def evaluate(self, success_count: int, suppressed: bool,
                 suppress_until_count: int = 0) -> int:
        if suppressed or success_count <= 0:
            return self.NONE
        if success_count > self.hard_stop_count:
            return self.NONE
        if suppress_until_count > 0 and success_count < suppress_until_count:
            return self.NONE
        if success_count not in self.triggers:
            return self.NONE
        return self.LAST_SHOW if success_count == self.hard_stop_count else self.SHOW
