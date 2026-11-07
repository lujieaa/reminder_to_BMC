# -*- coding: utf-8 -*-
"""赞助弹窗（渲染层）。

对外接口：
    - SupportPromptDialog：QDialog，负责展示文案 / 邮箱 / 二维码 / 按钮，
      并通过信号把用户操作抛给编排层
    - ThankYouDialog：赞助验证通过后的致谢窗体，倒计时自动关闭

依赖模块：config.FALLBACK_TITLE / DEFAULT_ICON_PATH
被依赖：core.SupportPrompt
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULT_ICON_PATH, FALLBACK_TITLE

_DIALOG_QSS = """
QDialog { background-color: #FFFBF5; }
QLabel#titleLabel { font-size: 22px; font-weight: 700; color: #4A2F1B; }
QLabel#subtitleLabel { font-size: 12px; color: #A8896E; }
QLabel#bodyLabel { font-size: 14px; color: #4A3526; line-height: 1.6; }
QLabel#emailLabel, QLabel#statusLabel { font-size: 12px; color: #6E5744; }
QLabel#qrCaption { font-size: 12px; color: #8A6F57; font-weight: 500; }
QLabel#noteLabel { font-size: 11px; color: #A89380; }
QLabel#qrLabel { background: #FFFFFF; border: 1px solid #F0E2D2; border-radius: 14px;
                 color: #B5A494; font-size: 12px; padding: 10px; }
QFrame#separator { color: #F2E4D4; }
QLineEdit { background: #FFF; border: 1px solid #EADAC8; border-radius: 8px;
            padding: 8px 10px; color: #6B5140; font-size: 12px;
            selection-background-color: #F5DDC4; }
QPushButton { background: #F3E6D8; color: #5A3D27; border: none;
              border-radius: 8px; padding: 9px 16px; font-size: 13px; }
QPushButton:hover { background: #E9D5BF; }
QPushButton:pressed { background: #DEC7AE; }
QPushButton:disabled { color: #B5A494; background: #F7EFE6; }
QPushButton#primaryButton { background: #D18B4A; color: #FFF; font-weight: 600; }
QPushButton#primaryButton:hover { background: #C47A3C; }
QPushButton#primaryButton:pressed { background: #B06A30; }
QPushButton#secondaryButton { background: #FFF3E6; color: #A85F2A;
                              border: 1px solid #EBC9A6; }
QPushButton#secondaryButton:hover { background: #FFE8CE; }
"""


# -- 布局工具 -------------------------------------------------------------


def _enable_height_for_width(label: QLabel) -> None:
    """让自动换行的 QLabel 参与 heightForWidth 布局。

    QLabel 默认 sizePolicy 不带 heightForWidth 标志，换行后的实际
    高度不会反馈给布局：窗口变矮/变窄时文本会被垂直截断。
    """
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)


# -- 二维码处理 -------------------------------------------------------------

# 码位 QLabel 为 260x293，去掉 padding/border 后内容区约 238x269
_QR_FIT_W, _QR_FIT_H = 238, 269


def _fit_qr(pixmap: QPixmap) -> QPixmap:
    """把二维码图片缩放到码位内容区。"""
    return pixmap.scaled(_QR_FIT_W, _QR_FIT_H,
                         Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _crop_to_card(pixmap: QPixmap) -> QPixmap:
    """裁掉纯色边距，只留白色卡片区域（二维码印在白卡上）。

    在缩略图上定位“近白色像素覆盖率足够高”的行（卡片主体），
    避免白色标题文字把包围盒撑到卡片之外；只扫描上部 80%，
    避开底部可能的支付平台标识带。
    """
    img = pixmap.toImage()
    small = img.scaledToWidth(160, Qt.SmoothTransformation)
    sw, sh = small.width(), small.height()
    scan_h = max(1, int(sh * 0.8))
    # 逐行统计近白色像素，卡片行的覆盖率远高于标题文字行
    white_rows = []
    for y in range(scan_h):
        count = 0
        for x in range(sw):
            c = small.pixelColor(x, y)
            if c.red() > 238 and c.green() > 238 and c.blue() > 238:
                count += 1
        white_rows.append(count)
    threshold = sw * 0.4
    rows = [y for y, n in enumerate(white_rows) if n > threshold]
    if not rows or (rows[-1] - rows[0]) < scan_h * 0.2:
        return pixmap  # 没找到明显卡片，原样返回
    y0, y1 = rows[0], rows[-1]
    x0, x1 = sw, -1
    for y in range(y0, y1 + 1):
        for x in range(sw):
            c = small.pixelColor(x, y)
            if c.red() > 238 and c.green() > 238 and c.blue() > 238:
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
    if x1 < 0 or (x1 - x0) < sw * 0.2:
        return pixmap
    scale = img.width() / sw
    margin = img.width() * 0.03
    left = max(0, int(x0 * scale - margin))
    top = max(0, int(y0 * scale - margin))
    right = min(img.width(), int((x1 + 1) * scale + margin))
    bottom = min(img.height(), int((y1 + 1) * scale + margin))
    return pixmap.copy(left, top, right - left, bottom - top)


def _split_dual_qr(pixmap: QPixmap):
    """把左右并排的双码图拆成两张，并各自裁到卡片区域。"""
    w, h = pixmap.width(), pixmap.height()
    left = pixmap.copy(0, 0, w // 2, h)
    right = pixmap.copy(w - w // 2, 0, w // 2, h)
    return _crop_to_card(left), _crop_to_card(right)


class _AdaptiveHeightDialog(QDialog):
    """最小高度随内容/窗口宽度自适应的对话框基类。

    Qt 不会把换行文本 heightForWidth 出的所需高度设为顶层窗口最小高度
    （minimumSize 按“只显示一行”计算），用户把窗口拖矮时正文第二行会被
    垂直截断。这里在尺寸或布局变化时，把“当前宽度下换行所需的最低高度”
    同步为窗口最小高度：窗口矮于内容时被顶住，拖窄时高度自动跟着长。
    """

    def event(self, ev: QEvent) -> bool:  # noqa: N802 (Qt 命名)
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            lay = self.layout()
            if lay is not None and lay.hasHeightForWidth():
                need = lay.totalHeightForWidth(self.width())
                if need > 0 and need != self.minimumHeight():
                    self.setMinimumHeight(need)
        return super().event(ev)


class SupportPromptDialog(_AdaptiveHeightDialog):
    dismissed = Signal(str)          # later / never / verified / closed
    support_clicked = Signal()
    verify_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None, icon_path: str = ""):
        super().__init__(parent)
        self._close_reason = "closed"
        self._busy = False
        self._backend_available = True
        self._email = ""
        self._email_subject = ""
        self._icon_path = icon_path or str(DEFAULT_ICON_PATH)
        self._build_ui()

    def _load_window_icon(self) -> None:
        icon = QIcon(self._icon_path)
        if not icon.isNull():
            self.setWindowIcon(icon)
            if self._title_icon_label is not None:
                pix = icon.pixmap(40, 40)
                self._title_icon_label.setPixmap(pix)

    # -- UI 构建 ----------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("可以请我喝杯咖啡吗？")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(600)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 22)
        root.setSpacing(14)

        # 标题行：讨喜的咖啡杯图标 + 标题
        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self._title_icon_label = QLabel()
        self._title_icon_label.setFixedSize(44, 44)
        self.title_label = QLabel(objectName="titleLabel")
        title_row.addWidget(self._title_icon_label)
        title_row.addWidget(self.title_label, 1)
        title_row.addStretch(1)

        self.subtitle_label = QLabel(objectName="subtitleLabel")
        sep = QFrame(objectName="separator")
        sep.setFrameShape(QFrame.HLine)

        self.body_label = QLabel(objectName="bodyLabel", wordWrap=True)
        self.body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # 声明 heightForWidth：布局按“实际宽度下换行后的高度”分配空间，
        # 拖窄窗口时最小高度随之增长，文本不再被垂直截断
        _enable_height_for_width(self.body_label)

        self.email_label = QLabel(objectName="emailLabel")
        self.email_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.copy_email_btn = QPushButton("复制邮箱")
        self.mail_btn = QPushButton("写邮件")
        email_row = QHBoxLayout()
        email_row.setSpacing(8)
        email_row.addWidget(self.email_label, 1)
        email_row.addWidget(self.copy_email_btn)
        email_row.addWidget(self.mail_btn)

        # 二维码：双码（支付宝/微信）并排显示，单码会话二维码居中显示。
        # 单个码必须足够大才能被手机扫上，所以双码时拆成两个独立码位。
        self.qr_label = QLabel(objectName="qrLabel", alignment=Qt.AlignCenter,
                               wordWrap=True, text="二维码加载中…")
        self.qr_label.setFixedSize(260, 293)
        self.qr_label_right = QLabel(objectName="qrLabel", alignment=Qt.AlignCenter)
        self.qr_label_right.setFixedSize(260, 293)
        self.qr_label_right.hide()
        qr_row = QHBoxLayout()
        qr_row.setSpacing(12)
        qr_row.addStretch(1)
        qr_row.addWidget(self.qr_label)
        qr_row.addWidget(self.qr_label_right)
        qr_row.addStretch(1)
        self.qr_caption = QLabel("扫码支持我一下 ♡",
                                 objectName="qrCaption", alignment=Qt.AlignCenter)

        self.status_label = QLabel(objectName="statusLabel", wordWrap=True, visible=False)
        self.note_label = QLabel("支持完全自愿，不赞助也不影响任何功能。",
                                 objectName="noteLabel", wordWrap=True)
        for wrapped in (self.status_label, self.note_label):
            _enable_height_for_width(wrapped)

        self.later_btn = QPushButton("稍后再说")
        self.never_btn = QPushButton("不再提醒")
        self.support_btn = QPushButton("去买咖啡", objectName="primaryButton")
        self.verify_btn = QPushButton("我已完成支持", objectName="secondaryButton")
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addWidget(self.later_btn)
        btn_row.addWidget(self.never_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.support_btn)
        btn_row.addWidget(self.verify_btn)

        root.addLayout(title_row)
        root.addWidget(self.subtitle_label)
        root.addWidget(sep)
        root.addWidget(self.body_label)
        root.addLayout(email_row)
        # 支付二维码只在外部支付页面展示，弹窗不再展示个人收款码。
        self.qr_label.hide()
        self.qr_label_right.hide()
        self.qr_caption.hide()
        root.addLayout(qr_row)
        root.addWidget(self.qr_caption, 0, Qt.AlignHCenter)
        root.addWidget(self.status_label)
        root.addWidget(self.note_label)
        root.addLayout(btn_row)

        self.setStyleSheet(_DIALOG_QSS)
        self._load_window_icon()

        self.later_btn.clicked.connect(lambda: self._close_with("later"))
        self.never_btn.clicked.connect(lambda: self._close_with("never"))
        self.support_btn.clicked.connect(self.support_clicked)
        self.verify_btn.clicked.connect(self.verify_clicked)
        self.copy_email_btn.clicked.connect(self._copy_email)
        self.mail_btn.clicked.connect(self._open_mail)
        self._update_buttons()

    # -- 对外接口 ----------------------------------------------------------

    def set_prompt_content(self, title: str, body: str, count: int, last_show: bool) -> None:
        title = title or FALLBACK_TITLE
        self.title_label.setText(title)
        self.setWindowTitle(title)
        suffix = " · 最后一次提醒" if last_show else ""
        self.subtitle_label.setText(f"第 {count} 次处理成功{suffix}")
        self.body_label.setText(body)

    def set_contact_email(self, email: str, subject: str) -> None:
        self._email, self._email_subject = email.strip(), subject
        has = bool(self._email)
        self.email_label.setText(f"反馈 / 评价请发邮件到：{self._email}")
        for w in (self.email_label, self.copy_email_btn, self.mail_btn):
            w.setVisible(has)

    def set_never_visible(self, visible: bool) -> None:
        self.never_btn.setVisible(visible)

    def set_payment_visible(self, visible: bool) -> None:
        """控制支付入口；二维码始终在外部支付页面展示。"""
        for w in (self.support_btn, self.verify_btn, self.note_label):
            w.setVisible(visible)
        self.qr_label.hide()
        self.qr_label_right.hide()
        self.qr_caption.hide()

    def set_backend_available(self, available: bool) -> None:
        self._backend_available = available
        self.verify_btn.setToolTip("" if available else "当前未配置校验服务，无法自动确认支持状态")
        self._update_buttons()

    def set_qr_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        # 二维码由支付页面承载，避免在弹窗中显示个人收款码。
        self.qr_label.hide()
        self.qr_label_right.hide()
        self.qr_caption.hide()
        if pixmap and not pixmap.isNull():
            self.qr_label.setText("")
            self.qr_label_right.setText("")
            if pixmap.width() > pixmap.height() * 1.2:
                # 双码并排图：拆成左右两张、裁掉边距，各占一个码位
                left, right = _split_dual_qr(pixmap)
                self.qr_label.setPixmap(_fit_qr(left))
                self.qr_label_right.setPixmap(_fit_qr(right))
                self.qr_label_right.show()
            else:
                # 单码（会话二维码）：居中独占一个码位
                self.qr_label.setPixmap(_fit_qr(pixmap))
                self.qr_label_right.hide()
        else:
            self.set_qr_placeholder("二维码暂不可用，请使用下方链接")

    def set_qr_placeholder(self, text: str) -> None:
        self.qr_label.setPixmap(QPixmap())
        self.qr_label.setText(text)
        self.qr_label_right.setPixmap(QPixmap())
        self.qr_label_right.setText("")
        self.qr_label_right.hide()
        self.qr_label.hide()
        self.qr_caption.hide()

    def set_busy(self, busy: bool, status: str = "") -> None:
        self._busy = busy
        self._update_buttons()
        if status:
            self.set_status(status, error=False)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
        self.status_label.setStyleSheet(
            "color: #B23B2E;" if error else "color: #6E5744;")

    def finish(self, reason: str) -> None:
        self._close_with(reason)

    # -- 内部 ---------------------------------------------------------------

    def reject(self) -> None:  # noqa: N802 (Qt 命名)
        reason, self._close_reason = self._close_reason, "closed"
        super().reject()
        self.dismissed.emit(reason)

    def _close_with(self, reason: str) -> None:
        self._close_reason = reason
        self.reject()

    def _update_buttons(self) -> None:
        self.support_btn.setEnabled(not self._busy)
        self.verify_btn.setEnabled(not self._busy and self._backend_available)

    def _copy_email(self) -> None:
        QApplication.clipboard().setText(self._email)
        self.set_status("邮箱已复制到剪贴板。")

    def _open_mail(self) -> None:
        QDesktopServices.openUrl(QUrl(f"mailto:{self._email}?subject={self._email_subject}"))

class ThankYouDialog(_AdaptiveHeightDialog):
    """验证通过后的致谢窗体：倒计时自动关闭，也可点按钮立即关闭。

    非模态、不阻塞主程序；复用暖色咖啡主题 QSS。
    """

    AUTO_CLOSE_SECONDS = 6

    def __init__(self, parent: Optional[QWidget] = None, icon_path: str = ""):
        super().__init__(parent)
        self._remaining = self.AUTO_CLOSE_SECONDS
        self._build_ui(icon_path or str(DEFAULT_ICON_PATH))
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_ui(self, icon_path: str) -> None:
        self.setWindowTitle("感谢支持")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)

        icon_label = QLabel(alignment=Qt.AlignCenter)
        icon_label.setFixedSize(64, 64)
        icon = QIcon(icon_path)
        if not icon.isNull():
            self.setWindowIcon(icon)
            icon_label.setPixmap(icon.pixmap(56, 56))

        title = QLabel("感谢支持 ♡", objectName="titleLabel", alignment=Qt.AlignCenter)
        body = QLabel(
            "已收到你的咖啡！\n你的支持是我继续改进的最大动力。\n以后不会再打扰你了。",
            objectName="bodyLabel", alignment=Qt.AlignCenter, wordWrap=True)
        _enable_height_for_width(body)
        self.countdown_label = QLabel(objectName="noteLabel", alignment=Qt.AlignCenter)
        self._update_countdown_text()

        self.ok_btn = QPushButton("好 ♡", objectName="primaryButton")
        self.ok_btn.clicked.connect(self.accept)

        root.addWidget(icon_label, 0, Qt.AlignHCenter)
        root.addWidget(title)
        root.addWidget(body)
        root.addWidget(self.countdown_label)
        root.addWidget(self.ok_btn, 0, Qt.AlignHCenter)

        self.setStyleSheet(_DIALOG_QSS)

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
        else:
            self._update_countdown_text()

    def _update_countdown_text(self) -> None:
        self.countdown_label.setText(f"本窗口将在 {self._remaining} 秒后自动关闭")
