# -*- coding: utf-8 -*-
"""模块编排（控制层）。

对外接口：
    - SupportPrompt：宿主入口，init 后每次成功操作调用 on_process_success()，
      内部串联 store / policy / catalog / dialog / 网络 / 二维码加载

依赖模块：
    - config（SupportConfig、常量）
    - store.LocalStore
    - policy.PromptPolicy
    - catalog.PromptCatalog
    - dialog.SupportPromptDialog

被依赖：__init__ 对外暴露
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from .catalog import PromptCatalog
from .config import (
    NEVER_BUTTON_FIRST_COUNT,
    VERIFY_POLL_INTERVAL_MS,
    VERIFY_POLL_TIMEOUT_MS,
    SupportConfig,
)
from .dialog import SupportPromptDialog, ThankYouDialog
from .policy import PromptPolicy
from .store import LocalStore


class SupportPrompt(QObject):
    """宿主入口：init 后每次成功操作调用 on_process_success()。"""

    IDLE, READY, PENDING, VERIFYING, VERIFIED, FAILED = range(6)

    prompt_shown = Signal(int)
    prompt_dismissed = Signal(str)
    support_verified = Signal()
    suppressed_changed = Signal(bool, str)

    def __init__(self, config: SupportConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        error = config.validate()
        if error:
            raise ValueError(f"[SupportPrompt] 配置非法：{error}")

        self._config = config
        self._parent_widget = parent
        self._store = LocalStore(config)
        self._catalog = PromptCatalog(config.prompts_file)
        self._policy = PromptPolicy(config.trigger_indices, config.hard_stop_count)
        self._nam = QNetworkAccessManager(self)

        self._state = self.IDLE
        self._dialog: Optional[SupportPromptDialog] = None
        self._session: dict = {}
        self._prompt_count = 0
        # 自动轮询状态：单发 QTimer 链式调度，结果到达后再排下一次
        self._poll_timer: Optional[QTimer] = None
        self._poll_started_at: Optional[datetime] = None
        # 致谢窗体（verified 后弹出，倒计时自动关闭）
        self._thanks_dialog: Optional[ThankYouDialog] = None

    # -- 公开 API -----------------------------------------------------------

    @property
    def state(self) -> int:
        return self._state

    @property
    def success_count(self) -> int:
        return self._store.success_count

    @property
    def is_suppressed(self) -> bool:
        return self._store.suppressed

    def on_process_success(self) -> None:
        """宿主每次“处理成功”时调用；模块自行决定是否弹窗。"""
        count = self._store.success_count + 1
        self._store.set("successCount", count)

        if self._store.suppressed:
            self._log("success_after_suppressed", successCount=count)
            return

        decision = self._policy.evaluate(count, False, self._store.suppress_until_count)
        if decision == PromptPolicy.NONE:
            return

        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return

        self._show_prompt(count, decision == PromptPolicy.LAST_SHOW)

    def reset_all(self) -> None:
        """测试/调试用：清空本地状态并关闭弹窗。"""
        self._stop_verify_polling()
        if self._thanks_dialog is not None:
            thanks, self._thanks_dialog = self._thanks_dialog, None
            thanks.deleteLater()
        if self._dialog is not None:
            dialog, self._dialog = self._dialog, None
            dialog.dismissed.disconnect()
            dialog.hide()
            dialog.deleteLater()
        self._session = {}
        self._state = self.IDLE
        self._store.reset()
        self.suppressed_changed.emit(False, "reset")

    # -- 弹窗流程 -----------------------------------------------------------

    def _show_prompt(self, count: int, last_show: bool) -> None:
        self._prompt_count = count
        self._session = {}
        self._state = self.READY

        title, body = self._catalog.text_for(count)
        cfg = self._config

        dialog = SupportPromptDialog(self._parent_widget, icon_path=cfg.icon_path)
        self._dialog = dialog
        dialog.set_prompt_content(title, body, count, last_show)
        dialog.set_contact_email(cfg.contact_email, cfg.contact_email_subject)
        # 前 3 次只给“稍后再说”；第 4 次起才出现“不再提醒”
        never_visible = cfg.allow_never_remind and count >= NEVER_BUTTON_FIRST_COUNT
        dialog.set_never_visible(never_visible)
        # 二维码不在弹窗中展示；点击按钮后打开支付页面。
        dialog.set_payment_visible(True)
        dialog.set_backend_available(bool(cfg.api_base_url))

        dialog.dismissed.connect(self._on_dismissed)
        dialog.support_clicked.connect(self._on_support_clicked)
        dialog.verify_clicked.connect(self._on_verify_clicked)

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._log("prompt_shown", successCount=count, lastShow=last_show)
        self.prompt_shown.emit(count)

    def _on_dismissed(self, reason: str) -> None:
        self._stop_verify_polling()
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.deleteLater()

        if reason == "never" and self._config.allow_never_remind:
            # “不再提醒”不是永久关闭，而是跳过 N 次成功后再恢复提醒
            skip = max(0, self._config.never_remind_skip_count)
            until = self._store.success_count + skip
            self._store.set_suppress_until_count(until)
            self._log("never_remind_interval",
                      skip=skip, suppressUntilCount=until)
            self.suppressed_changed.emit(False, f"never:{until}")

        self._log("prompt_dismissed", reason=reason)
        self.prompt_dismissed.emit(reason)
        self._session = {}
        if self._state != self.VERIFIED:
            self._state = self.IDLE

    def _on_support_clicked(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return

        if not self._config.api_base_url:
            self._open_checkout(dialog, self._config.checkout_url)
            dialog.set_status("当前版本未配置校验服务，可先通过链接支持。", error=True)
            return

        if self._session_valid():
            self._state = self.PENDING
            self._open_checkout(dialog, self._session["checkoutUrl"])
            return

        dialog.set_busy(True, "正在创建支持会话…")
        payload = {
            "appId": self._config.app_id,
            "platform": sys.platform,
            "language": "zh",
            "promptKey": str(self._prompt_count),
            "successCount": self._prompt_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._post_json("/support/session/create", payload, self._on_session_created)

    def _on_session_created(self, ok: bool, data: dict, error: str) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        dialog.set_busy(False)
        if not ok:
            self._log("support_session_failed", error=error)
            self._open_checkout(dialog, self._config.checkout_url)
            dialog.set_status("未能连接校验服务，可先通过链接支持；自动确认暂不可用。", error=True)
            return

        self._session = {
            "id": data.get("supportSessionId", ""),
            "checkoutUrl": self._absolutize(data.get("coffeeCheckoutUrl", "")),
            "qrPngUrl": self._absolutize(data.get("qrPngUrl", "")),
            "expiresAt": data.get("expiresAt", ""),
        }
        self._state = self.PENDING
        self._store.set("lastSupportSessionId", self._session["id"])
        self._log("support_session_created", sid=self._session["id"])

        url = self._session["checkoutUrl"]
        dialog.set_status("已打开支持页面，完成后点击“我已完成支持”。")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _on_verify_clicked(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        if not self._config.api_base_url:
            dialog.set_status("当前版本未配置校验服务，无法自动确认支持状态。", error=True)
            return
        if not self._session_valid():
            dialog.set_status("请先点击“去买咖啡”打开支持页面，再回来验证。", error=True)
            return
        if self._poll_started_at is not None:
            return  # 已在自动轮询中，忽略重复点击

        # 点一次即开始自动轮询，直到 已确认 / 未收到 / 会话过期 / 超时
        self._poll_started_at = datetime.now(timezone.utc)
        dialog.set_busy(True)
        dialog.verify_btn.setText("确认中（自动重试）…")
        dialog.set_status("正在验证支持状态，之后会自动重试，无需再点。")
        self._request_verify()

    def _request_verify(self) -> None:
        """发起一次 verify 请求；结果到达后由 _on_verify_result 决定是否再排下一次。"""
        dialog = self._dialog
        if dialog is None:
            self._stop_verify_polling()
            return
        if not self._session_valid():
            self._end_verify_polling(dialog)
            self._state = self.FAILED
            dialog.set_status("支持会话已过期，请重新点击“去买咖啡”。", error=True)
            return
        self._state = self.VERIFYING
        self._get_json(
            f"/support/verify?sid={self._session['id']}", self._on_verify_result)

    def _on_verify_result(self, ok: bool, data: dict, error: str) -> None:
        dialog = self._dialog
        if dialog is None:
            self._stop_verify_polling()
            return

        if ok and data.get("verified"):
            self._stop_verify_polling()
            self._state = self.VERIFIED
            self._set_suppressed(True, "verified")
            self._log("support_verified_result", result="success")
            self.support_verified.emit()
            dialog.finish("verified")
            self._show_thank_you()
            return

        status = data.get("status", "") if ok else ""
        if ok and status in ("rejected", "expired"):
            # 终态：停止轮询，给出明确提示
            self._end_verify_polling(dialog)
            self._state = self.FAILED
            message = (
                "支持会话已过期，请重新点击“去买咖啡”。" if status == "expired" else
                "收款方暂未确认收到款，请检查是否已支付成功；如有疑问可发邮件联系。")
            dialog.set_status(message, error=True)
            self._log("support_verified_result", result="failed", status=status)
            return

        if self._polling_timed_out():
            self._end_verify_polling(dialog)
            self._state = self.FAILED
            dialog.set_status("等待收款方确认超时，请稍后再点一次“我已完成支持”。",
                              error=True)
            self._log("support_verified_result", result="timeout",
                      status=status, error=error)
            return

        # pending 或网络抖动：保持轮询，无需用户再点
        if ok:
            dialog.set_status("收款方还在确认中，系统会自动重试，无需再点。")
        else:
            dialog.set_status("网络连接失败，自动重试中…", error=True)
        self._log("support_verified_result", result="polling",
                  status=status, error=error)
        self._schedule_verify_poll()

    def _schedule_verify_poll(self) -> None:
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.setSingleShot(True)
            self._poll_timer.timeout.connect(self._request_verify)
        self._poll_timer.start(VERIFY_POLL_INTERVAL_MS)

    def _stop_verify_polling(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
        self._poll_started_at = None

    def _end_verify_polling(self, dialog: SupportPromptDialog) -> None:
        """停止轮询并恢复按钮可用状态。"""
        self._stop_verify_polling()
        dialog.set_busy(False)
        dialog.verify_btn.setText("我已完成支持")

    def _polling_timed_out(self) -> bool:
        if self._poll_started_at is None:
            return True
        elapsed_ms = (datetime.now(timezone.utc)
                      - self._poll_started_at).total_seconds() * 1000
        return elapsed_ms >= VERIFY_POLL_TIMEOUT_MS

    # -- 致谢窗体 ------------------------------------------------------------

    def _show_thank_you(self) -> None:
        """verified 后弹出致谢窗体：倒计时自动关闭，不阻塞主程序。"""
        if self._thanks_dialog is not None:
            return
        dlg = ThankYouDialog(self._parent_widget, icon_path=self._config.icon_path)
        dlg.finished.connect(self._on_thanks_closed)
        self._thanks_dialog = dlg
        dlg.show()

    def _on_thanks_closed(self) -> None:
        dlg, self._thanks_dialog = self._thanks_dialog, None
        if dlg is not None:
            dlg.deleteLater()

    # -- 二维码加载（网络优先，本地兜底） ------------------------------------

    def _load_static_qr(self) -> None:
        """弹窗刚打开时：优先网络个人收款码，失败回落本地图片。"""
        if self._config.qr_image_url:
            self._fetch_image(self._config.qr_image_url, self._on_static_qr_loaded)
        else:
            self._apply_local_qr()

    def _on_static_qr_loaded(self, pixmap: Optional[QPixmap]) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        if pixmap is not None:
            dialog.set_qr_pixmap(pixmap)
        else:
            self._apply_local_qr()

    def _load_session_qr(self) -> None:
        """会话创建成功后：优先后端二维码，失败回落网络收款码，再回落本地。"""
        qr_url = self._session.get("qrPngUrl", "")
        if qr_url:
            self._fetch_image(qr_url, self._on_session_qr_loaded)
        else:
            self._load_static_qr()

    def _on_session_qr_loaded(self, pixmap: Optional[QPixmap]) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        if pixmap is not None:
            dialog.set_qr_pixmap(pixmap)
        else:
            self._load_static_qr()

    def _apply_local_qr(self) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        path = self._config.qr_image_local
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            dialog.set_qr_placeholder("二维码暂不可用，请使用下方链接")
        else:
            dialog.set_qr_pixmap(pixmap)

    def _fetch_image(self, url: str, callback: Callable[[Optional[QPixmap]], None]) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(self._config.http_timeout_ms)
        reply = self._nam.get(request)

        def _finished() -> None:
            reply.deleteLater()
            if reply.error() != QNetworkReply.NoError:
                self._log("qr_fetch_failed", url=url, error=reply.errorString())
                callback(None)
                return
            data = reply.readAll().data()
            if not data or len(data) > 4 * 1024 * 1024:
                callback(None)
                return
            pixmap = QPixmap()
            callback(pixmap if pixmap.loadFromData(data) else None)

        reply.finished.connect(_finished)

    # -- 网络 ---------------------------------------------------------------

    def _absolutize(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith(("http://", "https://")):
            return url
        return self._config.api_base_url.rstrip("/") + "/" + url.lstrip("/")

    def _endpoint(self, path_and_query: str) -> QUrl:
        return QUrl(self._config.api_base_url.rstrip("/") + path_and_query)

    def _post_json(self, path: str, payload: dict, callback) -> None:
        request = QNetworkRequest(self._endpoint(path))
        request.setHeader(QNetworkRequest.ContentTypeHeader,
                          "application/json; charset=utf-8")
        request.setTransferTimeout(self._config.http_timeout_ms)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        reply = self._nam.post(request, body)
        self._wire_reply(reply, callback)

    def _get_json(self, path_and_query: str, callback) -> None:
        request = QNetworkRequest(self._endpoint(path_and_query))
        request.setTransferTimeout(self._config.http_timeout_ms)
        reply = self._nam.get(request)
        self._wire_reply(reply, callback)

    def _wire_reply(self, reply: QNetworkReply, callback) -> None:
        def _finished() -> None:
            reply.deleteLater()
            if reply.error() != QNetworkReply.NoError:
                callback(False, {}, reply.errorString())
                return
            try:
                root = json.loads(bytes(reply.readAll()).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                callback(False, {}, "响应不是有效 JSON")
                return
            if root.get("code", 0) != 0:
                callback(False, {}, str(root.get("msg", "服务器错误")))
                return
            callback(True, root.get("data") or {}, "")

        reply.finished.connect(_finished)

    # -- 状态与日志 -----------------------------------------------------------

    def _session_valid(self) -> bool:
        if not self._session.get("id") or not self._session.get("checkoutUrl"):
            return False
        expires = self._session.get("expiresAt", "")
        if expires:
            try:
                exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if exp <= datetime.now(timezone.utc):
                    return False
            except ValueError:
                pass
        return True

    def _open_checkout(self, dialog: SupportPromptDialog, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))
        dialog.set_status("已打开支持页面，完成后点击“我已完成支持”。")

    def _set_suppressed(self, value: bool, reason: str) -> None:
        previous = self._store.suppressed
        self._store.set_suppressed(value, reason)
        if previous != value:
            self._log("suppressed_set", suppressed=value, reason=reason)
            self.suppressed_changed.emit(value, reason)

    def _log(self, event: str, **payload) -> None:
        if self._config.debug_logging:
            print(f"[SupportPrompt] {event} {payload}", file=sys.stderr)
