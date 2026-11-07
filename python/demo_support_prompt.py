# -*- coding: utf-8 -*-
"""SupportPrompt Python 版演示宿主。

运行：
    python python/demo_support_prompt.py

联调完整流程（创建会话 → 模拟支付 → 验证 → 永久关闭）：
    1. 先启动 mock 后端：  python tools/mock_backend.py
    2. 再运行本 demo，点击“模拟一次处理成功”
"""

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support_prompt import SupportConfig, SupportPrompt  # noqa: E402

def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("SupportPromptDemo")
    app.setApplicationName("SupportPromptDemoPy")

    window = QWidget()
    window.setWindowTitle("SupportPrompt 模块演示（Python 版）")
    window.resize(720, 520)
    root = QVBoxLayout(window)

    hint = QLabel(
        "先运行 python tools/mock_backend.py，可完整体验："
        "创建会话 → 打开支付页 → 验证成功 → 永久关闭提示。")
    hint.setWordWrap(True)
    count_label = QLabel()
    process_btn = QPushButton("模拟一次处理成功（PDF）")
    reset_btn = QPushButton("重置全部状态")
    log_view = QPlainTextEdit(readOnly=True,
                              placeholderText="模块事件会显示在这里")

    row = QHBoxLayout()
    row.addWidget(process_btn)
    row.addWidget(reset_btn)
    row.addStretch(1)
    root.addWidget(hint)
    root.addWidget(count_label)
    root.addLayout(row)
    root.addWidget(log_view, 1)

    config = SupportConfig(
        app_id="supportprompt-demo-py",
        api_base_url="http://127.0.0.1:8787",   # 留空字符串 = 离线模式
        contact_email="281299956@qq.com",
        checkout_url="https://www.buymeacoffee.com/lujieaa",
        # hard_stop_count 默认 40，trigger_indices 默认覆盖到 40
        debug_logging=True,
    )
    module = SupportPrompt(config, parent=window)

    def refresh() -> None:
        state_names = ["Idle", "ReadyToSupport", "SupportPending",
                       "SupportVerifying", "SupportVerified", "SupportFailed"]
        suppressed = "已永久关闭提示" if module.is_suppressed else "未关闭提示"
        count_label.setText(
            f"已成功处理 {module.success_count} 次 · {suppressed} · "
            f"状态：{state_names[module.state]}")

    def on_success() -> None:
        module.on_process_success()
        refresh()
        log_view.appendPlainText(f"success_count = {module.success_count}")

    def on_reset() -> None:
        module.reset_all()
        log_view.appendPlainText("---- 已重置本地状态 ----")
        refresh()

    module.prompt_dismissed.connect(
        lambda reason: (log_view.appendPlainText(f"prompt_dismissed: {reason}"), refresh()))
    module.suppressed_changed.connect(
        lambda value, reason: log_view.appendPlainText(
            f"suppressed_changed: {value} ({reason})"))
    module.support_verified.connect(
        lambda: log_view.appendPlainText("support_verified ✔ 已永久关闭提示"))

    process_btn.clicked.connect(on_success)
    reset_btn.clicked.connect(on_reset)

    refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
