# -*- coding: utf-8 -*-
"""会话存储（数据层）。

对外接口：
    - SessionStore：create / get / mark / is_expired / all_sorted

依赖模块：仅标准库
被依赖：server

持久化策略：
    默认内存存储；设置 SNAPSHOT_PATH 环境变量后，会在每次写操作后
    把会话快照写入该文件，并在启动时从该文件恢复（用于云函数热实例
    间保留会话数据）。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


class SessionStore:
    """线程安全的会话表。confirmed: None=待确认 / "paid"=已支付 / "rejected"=未收到。

    通过 SNAPSHOT_PATH 环境变量开启快照持久化（文件存 JSON 字典）。
    适合云函数 / 容器环境：热实例恢复数据，冷启动最多丢掉未持久化的那一个会话。
    """

    def __init__(self, ttl_seconds: int = 30 * 60):
        self._ttl = ttl_seconds
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._snapshot_path = os.environ.get("SNAPSHOT_PATH", "").strip()
        if self._snapshot_path:
            self._load_snapshot()

    # -- 公有 API ------------------------------------------------------------

    def create(self, app_id: str, prompt_key: str, success_count: int) -> dict:
        sid = secrets.token_urlsafe(18)
        created = now_utc()
        expires = created + timedelta(seconds=self._ttl)
        session = {
            "sid": sid,
            "appId": app_id,
            "promptKey": prompt_key,
            "successCount": success_count,
            "createdAt": iso(created),
            "expiresAt": iso(expires),
            "confirmed": None,
            "qrText": "",
            "channelOrderNo": "",
        }
        with self._lock:
            self._sessions[sid] = session
            self._trim_expired_locked()
            snapshot_body = dict(self._sessions) if self._snapshot_path else None
        if snapshot_body is not None:
            self._write_snapshot(snapshot_body)
        return session

    def get(self, sid: str) -> dict | None:
        with self._lock:
            return self._sessions.get(sid)

    def mark(self, sid: str, state: str, channel_order_no: str = "") -> bool:
        """state: "paid" / "rejected"。返回会话是否存在。"""
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return False
            session["confirmed"] = state
            session["confirmedAt"] = iso(now_utc())
            if channel_order_no:
                session["channelOrderNo"] = channel_order_no
            snapshot_body = (dict(self._sessions)
                             if (self._snapshot_path and state == "paid") else None)
        if snapshot_body is not None:
            self._write_snapshot(snapshot_body)
        return True

    def set_qr_text(self, sid: str, qr_text: str) -> None:
        with self._lock:
            session = self._sessions.get(sid)
            if session is not None:
                session["qrText"] = qr_text

    def is_expired(self, session: dict) -> bool:
        expires = datetime.fromisoformat(session["expiresAt"].replace("Z", "+00:00"))
        return now_utc() > expires

    def all_sorted(self) -> list[tuple[str, dict]]:
        with self._lock:
            items = list(self._sessions.items())
        return sorted(items, key=lambda kv: kv[1].get("createdAt", ""), reverse=True)

    # -- 持久化 ------------------------------------------------------------

    def _trim_expired_locked(self) -> None:
        """清理已过期的会话（写操作时顺便做）。"""
        now = now_utc()
        drop = [sid for sid, s in self._sessions.items()
                if datetime.fromisoformat(s["expiresAt"].replace("Z", "+00:00")) <= now]
        for sid in drop:
            self._sessions.pop(sid, None)

    def _load_snapshot(self) -> None:
        try:
            with open(self._snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        with self._lock:
            now = now_utc()
            for sid, s in data.items():
                exp_str = s.get("expiresAt", "")
                try:
                    exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if exp > now:
                    self._sessions[sid] = s

    def _write_snapshot(self, body: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self._snapshot_path) or ".", exist_ok=True)
            with open(self._snapshot_path, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
        except OSError:
            pass  # 快照失败不影响主流程
