#include <supportprompt/supportprompt.h>

#include <QApplication>
#include <QHBoxLayout>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QStringList>
#include <QTime>
#include <QVBoxLayout>
#include <QWidget>

namespace {

QString stateName(SupportPrompt::SupportPrompt::State state)
{
    using State = SupportPrompt::SupportPrompt::State;
    switch (state) {
    case State::Idle:
        return QStringLiteral("Idle");
    case State::ReadyToSupport:
        return QStringLiteral("ReadyToSupport");
    case State::SupportPending:
        return QStringLiteral("SupportPending");
    case State::SupportVerifying:
        return QStringLiteral("SupportVerifying");
    case State::SupportVerified:
        return QStringLiteral("SupportVerified");
    case State::SupportFailed:
        return QStringLiteral("SupportFailed");
    }
    return QStringLiteral("Unknown");
}

QString payloadToText(const QVariantMap &payload)
{
    QStringList parts;
    for (auto it = payload.constBegin(); it != payload.constEnd(); ++it)
        parts << QStringLiteral("%1=%2").arg(it.key(), it.value().toString());
    return parts.join(QStringLiteral(", "));
}

} // namespace

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    app.setOrganizationName(QStringLiteral("SupportPromptDemo"));
    app.setApplicationName(QStringLiteral("SupportPromptDemo"));

    QWidget window;
    window.setWindowTitle(QStringLiteral("SupportPrompt 模块演示"));
    window.resize(760, 560);

    auto *root = new QVBoxLayout(&window);
    root->setContentsMargins(24, 20, 24, 20);
    root->setSpacing(12);

    auto *title = new QLabel(QStringLiteral("处理成功后评价/赞助弹窗模块（Qt）"), &window);
    title->setStyleSheet(QStringLiteral("font-size: 20px; font-weight: 600; color: #4A2F1B;"));

    auto *hint = new QLabel(
        QStringLiteral("先运行 python tools/mock_backend.py，可完整体验："
                       "创建会话 → 打开支付页 → 验证成功 → 永久关闭提示。"),
        &window);
    hint->setWordWrap(true);
    hint->setStyleSheet(QStringLiteral("color: #7A6A5C; font-size: 12px;"));

    auto *countLabel = new QLabel(&window);
    countLabel->setStyleSheet(QStringLiteral("font-size: 14px; color: #3E2B1F;"));

    auto *processBtn = new QPushButton(QStringLiteral("模拟一次处理成功（PDF）"), &window);
    auto *resetBtn = new QPushButton(QStringLiteral("重置全部状态"), &window);

    auto *buttonRow = new QHBoxLayout();
    buttonRow->addWidget(processBtn);
    buttonRow->addWidget(resetBtn);
    buttonRow->addStretch(1);

    auto *logView = new QPlainTextEdit(&window);
    logView->setReadOnly(true);
    logView->setPlaceholderText(QStringLiteral("模块事件会显示在这里"));

    root->addWidget(title);
    root->addWidget(hint);
    root->addWidget(countLabel);
    root->addLayout(buttonRow);
    root->addWidget(logView, 1);

    window.setStyleSheet(QStringLiteral(R"(
        QWidget { background-color: #FAF6F1; font-size: 13px; }
        QPushButton {
            background-color: #C87941; color: #FFFFFF; border: none;
            border-radius: 6px; padding: 9px 16px;
        }
        QPushButton:hover { background-color: #B76C36; }
        QPlainTextEdit {
            background-color: #FFFFFF; border: 1px solid #E8D9CB;
            border-radius: 8px; color: #5A4636; font-family: Consolas, monospace;
        }
    )"));

    auto *module = new SupportPrompt::SupportPrompt(&window);

    SupportPrompt::Config config;
    config.appId = QStringLiteral("supportprompt-demo");
    config.apiBaseUrl = QUrl(QStringLiteral("http://127.0.0.1:8787"));
    config.contactEmail = QStringLiteral("281299956@qq.com");
    config.contactEmailSubject = QStringLiteral("SupportPrompt Demo 使用反馈");
    config.fallbackCheckoutUrl = QUrl(QStringLiteral("https://www.buymeacoffee.com/yourname"));
    config.fallbackQrImagePath = QStringLiteral(":/demo/demo_qr.png");
    config.iconPath = QStringLiteral(":/supportprompt/coffee_icon.jpg");
    config.organization = QStringLiteral("SupportPromptDemo");
    config.application = QStringLiteral("SupportPromptDemo");
    config.debugLogging = true;

    const bool initialized = module->init(config, &window);
    if (!initialized) {
        logView->appendPlainText(QStringLiteral("[错误] 模块初始化失败，请检查配置。"));
    }

    auto refresh = [&]() {
        const QString suppression = module->isSuppressed()
            ? QStringLiteral("已永久关闭提示")
            : QStringLiteral("未关闭提示");
        countLabel->setText(QStringLiteral("已成功处理 %1 次 · %2 · 状态：%3")
                                .arg(module->successCount())
                                .arg(suppression, stateName(module->state())));
    };

    auto appendEvent = [&](const QString &name, const QVariantMap &payload) {
        logView->appendPlainText(
            QStringLiteral("[%1] %2  %3")
                .arg(QTime::currentTime().toString(QStringLiteral("HH:mm:ss")),
                     name, payloadToText(payload)));
    };

    QObject::connect(processBtn, &QPushButton::clicked, &window, [&]() {
        SupportPrompt::Context context;
        context.appVersion = QStringLiteral("1.0.0");
        context.platform = QStringLiteral("demo");
        context.lastProcessedFileType = QStringLiteral("pdf");
        module->onProcessSuccess(context);
        refresh();
    });

    QObject::connect(resetBtn, &QPushButton::clicked, &window, [&]() {
        module->resetAll();
        logView->appendPlainText(QStringLiteral("---- 已重置本地状态 ----"));
        refresh();
    });

    QObject::connect(module, &SupportPrompt::SupportPrompt::eventLogged, &window,
                     [&](const QString &name, const QVariantMap &payload) {
                         appendEvent(name, payload);
                     });

    QObject::connect(module, &SupportPrompt::SupportPrompt::promptDismissed, &window,
                     [&](const QString &reason) {
                         appendEvent(QStringLiteral("promptDismissed"),
                                     {{QStringLiteral("reason"), reason}});
                         refresh();
                     });

    QObject::connect(module, &SupportPrompt::SupportPrompt::suppressedChanged, &window,
                     [&](bool suppressed, const QString &reason) {
                         appendEvent(QStringLiteral("suppressedChanged"),
                                     {{QStringLiteral("suppressed"), suppressed},
                                      {QStringLiteral("reason"), reason}});
                         refresh();
                     });

    QObject::connect(module, &SupportPrompt::SupportPrompt::supportVerified, &window,
                     [&]() {
                         appendEvent(QStringLiteral("supportVerified"), {});
                         refresh();
                     });

    refresh();
    window.show();
    return app.exec();
}
