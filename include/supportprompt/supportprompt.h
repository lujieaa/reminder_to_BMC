#pragma once

#include "supportpromptconfig.h"

#include <QDateTime>
#include <QImage>
#include <QObject>
#include <QPointer>
#include <QVariantMap>
#include <QWidget>

#include <functional>
#include <memory>

namespace SupportPrompt {

class LocalStore;
class PromptCatalog;
class PromptPolicy;
class SupportClient;
class SupportPromptDialog;

// 使用方式（宿主侧）：
//   auto *prompt = new SupportPrompt::SupportPrompt(this);
//   SupportPrompt::Config cfg;
//   cfg.appId = "my-pdf-tool";
//   cfg.apiBaseUrl = QUrl("https://api.example.com");
//   cfg.contactEmail = "you@example.com";
//   cfg.fallbackQrImagePath = ":/images/coffee_qr.png";
//   prompt->init(cfg, mainWindow);
//
//   // 每次业务处理成功后调用；模块自行决定是否弹窗
//   prompt->onProcessSuccess(SupportPrompt::Context{appVersion, platform, "pdf"});
//
// 设计原则：模块只负责提示与校验，任何网络/配置异常都不会影响宿主核心功能。
class SupportPrompt : public QObject
{
    Q_OBJECT

public:
    enum class State {
        Idle,            // 未展示
        ReadyToSupport,  // 弹窗已展示，支持会话未创建或已过期
        SupportPending,  // 已创建会话，等待用户支付
        SupportVerifying,// 已点“我已完成支持”，正在验证
        SupportVerified, // verified=true => suppressed=true
        SupportFailed    // verified=false 或网络失败，可重试
    };
    Q_ENUM(State)

    explicit SupportPrompt(QObject *parent = nullptr);
    ~SupportPrompt() override;

    // 初始化；configuration 非法时返回 false（宿主应忽略并继续正常运行）
    bool init(const Config &config, QWidget *parentWindow = nullptr);

    // 宿主每次“处理成功”时调用
    void onProcessSuccess(const Context &context = Context());

    bool isSuppressed() const;
    int successCount() const;
    State state() const;
    const Config &config() const;

    // 可选：注入本地二维码生成器（入参为待编码 URL，返回二维码图片）。
    // 返回空图时回落到为后端返回的二维码图片 / fallbackQrImagePath。
    // 注意：该回调在 UI 线程同步调用，宿主应确保快速返回（耗时生成请自行缓存）。
    void setQrCodeProvider(std::function<QImage(const QString &url)> provider);

    // 仅用于测试/Demo：清空本地状态并关闭弹窗
    void resetAll();

signals:
    void promptShown(int successCount, int triggerIndex);
    void promptDismissed(const QString &reason); // later / never / verified / closed
    void supportVerified();
    void suppressedChanged(bool suppressed, const QString &reason);
    void eventLogged(const QString &event, const QVariantMap &payload);

private:
    void teardown();
    void showPrompt(int count, bool lastShow, const Context &context);
    void handleDialogDismissed(const QString &reason);
    void handleSupportClicked();
    void handleVerifyClicked();
    void doVerify();
    void loadSessionQr(const QUrl &qrUrl);
    void applyFallbackCheckout();
    void applyStaticQr(const QUrl &url);
    void setSuppressed(bool value, const QString &reason);
    void logEvent(const QString &name, const QVariantMap &payload);
    bool sessionValid() const;
    QString platformName() const;

    Config m_config;
    QPointer<QWidget> m_parentWindow;
    LocalStore *m_store = nullptr;
    PromptCatalog *m_catalog = nullptr;
    SupportClient *m_client = nullptr;
    std::unique_ptr<PromptPolicy> m_policy;
    std::function<QImage(const QString &)> m_qrProvider;

    struct SessionInfo {
        QString id;
        QUrl checkoutUrl;
        QUrl qrPngUrl;
        QDateTime expiresAt;
    };
    SessionInfo m_session;

    QPointer<SupportPromptDialog> m_dialog;
    int m_promptSuccessCount = 0;
    QString m_promptKey;
    State m_state = State::Idle;
    bool m_initialized = false;
};

} // namespace SupportPrompt
