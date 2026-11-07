# -*- coding: utf-8 -*-
"""本地持久化（数据层）。

对外接口：
    - LocalStore：基于 QSettings(IniFormat) 的 KV 存储，封装
      success_count / suppressed / suppress_until_count 等属性

依赖模块：config.SupportConfig（取 settings_* 字段）
被依赖：core.SupportPrompt
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from .config import SupportConfig


class LocalStore:
    def __init__(self, config: SupportConfig):
        self._group = config.settings_group or "SupportPrompt"
        self._s = QSettings(
            QSettings.IniFormat,
            QSettings.UserScope,
            config.settings_org or "SupportPrompt",
            config.settings_app or config.app_id,
        )

    def _key(self, name: str) -> str:
        return f"{self._group}/{name}"

    def get(self, name: str, default=None):
        return self._s.value(self._key(name), default)

    def set(self, name: str, value) -> None:
        self._s.setValue(self._key(name), value)
        self._s.sync()

    @property
    def success_count(self) -> int:
        try:
            return int(self.get("successCount", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def suppressed(self) -> bool:
        return str(self.get("suppressed", "false")).lower() in ("true", "1")

    @property
    def suppress_until_count(self) -> int:
        try:
            return int(self.get("suppressUntilCount", 0))
        except (TypeError, ValueError):
            return 0

    def set_suppressed(self, value: bool, reason: str = "") -> None:
        self.set("suppressed", value)
        self.set("suppressedReason", reason if value else "")
        if value and reason == "verified":
            self.set("supportVerified", True)

    def set_suppress_until_count(self, value: int) -> None:
        self.set("suppressUntilCount", max(0, int(value)))

    def reset(self) -> None:
        self._s.remove(self._group)
        self._s.sync()
