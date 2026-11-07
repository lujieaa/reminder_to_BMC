# -*- coding: utf-8 -*-
"""文案目录（数据层）。

对外接口：
    - PromptCatalog：加载 prompts_zh.json，按 trigger 序号返回 (title, body)

依赖模块：config.FALLBACK_TITLE / FALLBACK_BODY / DEFAULT_PROMPTS_PATH
被依赖：core.SupportPrompt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import DEFAULT_PROMPTS_PATH, FALLBACK_BODY, FALLBACK_TITLE


class PromptCatalog:
    def __init__(self, path: str = ""):
        self._texts = {}
        target = Path(path) if path else DEFAULT_PROMPTS_PATH
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            for item in data.get("prompts", []):
                trigger = int(item.get("trigger", 0))
                body = str(item.get("body", "")).strip()
                if trigger > 0 and body:
                    self._texts[trigger] = (item.get("title", "").strip(), body)
        except (OSError, ValueError) as exc:
            print(f"[SupportPrompt] 文案加载失败，使用兜底文案: {exc}", file=sys.stderr)

    def text_for(self, trigger: int) -> tuple:
        return self._texts.get(trigger, (FALLBACK_TITLE, FALLBACK_BODY.format(n=trigger)))
