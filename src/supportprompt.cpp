#include <supportprompt/supportprompt.h>
#include <supportprompt/promptpolicy.h>

#include "localstore.h"
#include "promptcatalog.h"
#include "supportclient.h"
#include "supportpromptdialog.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDebug>
#include <QDesktopServices>
#include <QSysInfo>

#include <vector>
#include <utility>

static void initSupportPromptResources()
{
    Q_INIT_RESOURCE(supportprompt);
}

namespace SupportPrompt {

SupportPrompt::SupportPrompt(QObject *parent)
    : QObject(parent)
{
    initSupportPromptResources();
}

SupportPrompt::~SupportPrompt()
{
    teardown();
}

bool SupportPrompt::init(const Config &config, QWidget *parentWindow)
{
    Config effective = config;
    if (effective.triggerIndices.isEmpty())
        effective.triggerIndices = defaultTriggerIndices();

    QString error;
    if (!effective.isValid(&error)) {
        qWarning().noquote() << "[SupportPrompt] init 失败：" << error;
        return false;
    }

    if (m_initialized)
        teardown();

    m_config = effective;
    m_parentWindow = parentWindow;
    m_store = new LocalStore(effective);

    m_catalog = new PromptCatalog();
    QString catalogError;
    if (!m_catalog->load(effective.promptsFilePath, &catalogError))
        qWarning().noquote() << "[SupportPrompt] 文案加载失败，将使用内置兜底文案：" << catalogError;

    std::vector<int> triggers;
    for (int value : effective.triggerIndices) {
        if (value > 0)
            triggers.push_back(value);
    }
    if (triggers.empty()) {
        const QVector<int> defaults = defaultTriggerIndices();
        for (int value : defaults)
            triggers.push_back(value);
    }
    m_policy.reset(new PromptPolicy(std::move(triggers), effective.hardStopCount));

    if (!effective.apiBaseUrl.isEmpty())
        m_client = new SupportClient(effective, this);

    m_initialized = true;
    logEvent(QStringLiteral("module_initialized"),
             {{QStringLiteral("offlineMode"), m_client == nullptr}});
    return true;
}

void SupportPrompt::onProcessSuccess(const Context &context)
{
    if (!m_initialized || !m_store || !m_policy)
        return;

    const int count = m_store->successCount() + 1;
    m_store->setSuccessCount(count);

    if (m_store->suppressed()) {
        logEvent(QStringLiteral("success_after_suppressed"),
                 {{QStringLiteral("successCount"), count}});
        return;
    }

    const int suppressUntil = m_store ? m_store->suppressUntilCount() : 0;
    const PromptPolicy::Decision decision = m_policy->evaluate(count, false, suppressUntil);
    if (decision == PromptPolicy::Decision::None)
        return;

    if (m_dialog) {
        m_dialog->raise();
        m_dialog->activateWindow();
        return;
    }

    m_store->setLastPromptAt(QDateTime::currentDateTimeUtc());
    m_store->setPromptShownCount(m_store->promptShownCount() + 1);
    showPrompt(count, decision == PromptPolicy::Decision::LastShow, context);
}

bool SupportPrompt::isSuppressed() const
{
    return m_store && m_store->suppressed();
}

int SupportPrompt::successCount() const
{
    return m_store ? m_store->successCount() : 0;
}

SupportPrompt::State SupportPrompt::state() const
{
    return m_state;
}

const Config &SupportPrompt::config() const
{
    return m_config;
}

void SupportPrompt::setQrCodeProvider(std::function<QImage(const QString &)> provider)
{
    m_qrProvider = std::move(provider);
}

void SupportPrompt::resetAll()
{
    if (m_dialog) {
        SupportPromptDialog *dialog = m_dialog.data();
        m_dialog = nullptr;
        dialog->disconnect(this);
        dialog->hide();
        dialog->deleteLater();
    }

    m_session = SessionInfo{};
    m_state = State::Idle;
    if (m_store)
        m_store->reset();

    emit suppressedChanged(false, QStringLiteral("reset"));
}

void SupportPrompt::showPrompt(int count, bool lastShow, const Context &context)
{
    m_promptSuccessCount = count;
    m_promptKey = QString::number(count);
    m_session = SessionInfo{};
    m_state = State::ReadyToSupport;

    const PromptText text = m_catalog ? m_catalog->textFor(count)
                                      : PromptCatalog::fallbackFor(count);

    auto *dialog = new SupportPromptDialog(m_parentWindow.data(), m_config.iconPath);
    m_dialog = dialog;

    dialog->setPromptContent(text, count, lastShow);
    dialog->setContactEmail(m_config.contactEmail, m_config.contactEmailSubject);
    // 前 3 次只给“稍后再说”；第 4 次起才出现“不再提醒”
    const bool neverVisible = m_config.allowNeverRemind && count >= 4;
    dialog->setNeverRemindVisible(neverVisible);
    dialog->setBackendAvailable(m_client != nullptr);

    connect(dialog, &SupportPromptDialog::dismissed, this,
            &SupportPrompt::handleDialogDismissed);
    connect(dialog, &SupportPromptDialog::supportClicked, this,
            &SupportPrompt::handleSupportClicked);
    connect(dialog, &SupportPromptDialog::verifyClicked, this,
            &SupportPrompt::handleVerifyClicked);
    connect(dialog, &SupportPromptDialog::buttonClicked, this,
            [this](const QString &button) {
                logEvent(QStringLiteral("button_click"),
                         {{QStringLiteral("button"), button}});
            });

    dialog->show();
    dialog->raise();
    dialog->activateWindow();

    QVariantMap payload{
        {QStringLiteral("successCount"), count},
        {QStringLiteral("triggerIndex"), count},
        {QStringLiteral("lastShow"), lastShow},
    };
    if (!context.appVersion.isEmpty())
        payload.insert(QStringLiteral("appVersion"), context.appVersion);
    if (!context.lastProcessedFileType.isEmpty())
        payload.insert(QStringLiteral("fileType"), context.lastProcessedFileType);
    logEvent(QStringLiteral("prompt_shown"), payload);

    emit promptShown(count, count);
}

void SupportPrompt::handleDialogDismissed(const QString &reason)
{
    SupportPromptDialog *dialog = m_dialog.data();
    m_dialog = nullptr;
    if (dialog)
        dialog->deleteLater();

    if (reason == QStringLiteral("never") && m_config.allowNeverRemind && m_store) {
        // “不再提醒”不是永久关闭，而是跳过 N 次成功后再恢复提醒
        const int skip = qMax(0, m_config.neverRemindSkipCount);
        const int until = m_store->successCount() + skip;
        m_store->setSuppressUntilCount(until);
        logEvent(QStringLiteral("never_remind_interval"),
                 {{QStringLiteral("skip"), skip},
                  {QStringLiteral("suppressUntilCount"), until}});
        emit suppressedChanged(false, QStringLiteral("never:%1").arg(until));
    }

    logEvent(QStringLiteral("prompt_dismissed"),
             {{QStringLiteral("reason"), reason}});
    emit promptDismissed(reason);

    m_session = SessionInfo{};
    if (m_state != State::SupportVerified)
        m_state = State::Idle;
}

void SupportPrompt::handleSupportClicked()
{
    if (!m_initialized || !m_dialog)
        return;

    if (!m_client) {
        applyFallbackCheckout();
        m_dialog->setStatus(
            QStringLiteral("当前版本未配置校验服务，可先通过链接支持。"), true);
        return;
    }

    if (sessionValid()) {
        m_state = State::SupportPending;
        m_dialog->setStatus(
            QStringLiteral("已打开支持页面，完成后点击“我已完成支持”。"), false);
        QDesktopServices::openUrl(m_session.checkoutUrl);
        return;
    }

    m_dialog->setBusy(true, QStringLiteral("正在创建支持会话…"));

    const QPointer<SupportPromptDialog> dialog = m_dialog;
    m_client->createSession(
        m_promptKey, m_promptSuccessCount,
        [this, dialog](bool ok, const SupportSession &session, const QString &error) {
            if (!dialog)
                return;

            dialog->setBusy(false);
            if (!ok) {
                logEvent(QStringLiteral("support_session_failed"),
                         {{QStringLiteral("error"), error}});
                applyFallbackCheckout();
                return;
            }

            m_session.id = session.id;
            m_session.checkoutUrl = session.checkoutUrl;
            m_session.qrPngUrl = session.qrPngUrl;
            m_session.expiresAt = session.expiresAt;
            m_state = State::SupportPending;

            if (m_store)
                m_store->setLastSupportSessionId(session.id);

            dialog->setStatus(
                QStringLiteral("已打开支持页面，完成后点击“我已完成支持”。"), false);
            QDesktopServices::openUrl(session.checkoutUrl);

            logEvent(QStringLiteral("support_session_created"),
                     {{QStringLiteral("sid"), session.id}});
        });
}

void SupportPrompt::handleVerifyClicked()
{
    if (!m_initialized || !m_dialog)
        return;

    if (!m_client) {
        m_dialog->setStatus(
            QStringLiteral("当前版本未配置校验服务，无法自动确认支持状态。"), true);
        return;
    }

    if (!sessionValid()) {
        m_dialog->setStatus(
            QStringLiteral("请先点击“去买咖啡”打开支持页面，再回来验证。"), true);
        return;
    }

    doVerify();
}

void SupportPrompt::doVerify()
{
    const QPointer<SupportPromptDialog> dialog = m_dialog;
    if (!dialog || !m_client || m_session.id.isEmpty())
        return;

    m_state = State::SupportVerifying;
    dialog->setBusy(true, QStringLiteral("正在验证支持状态…"));

    m_client->verify(
        m_session.id,
        [this, dialog](bool ok, bool verified, const QString &status,
                       const QString &error, const QString &errorCode) {
            if (!dialog)
                return;

            dialog->setBusy(false);
            if (!ok) {
                m_state = State::SupportFailed;
                dialog->setStatus(
                    QStringLiteral("验证失败：%1，请稍后重试。").arg(error), true);
                logEvent(QStringLiteral("support_verified_result"),
                         {{QStringLiteral("result"), QStringLiteral("failed")},
                          {QStringLiteral("error"), error},
                          {QStringLiteral("errorCode"), errorCode}});
                return;
            }

            if (verified) {
                m_state = State::SupportVerified;
                setSuppressed(true, QStringLiteral("verified"));
                logEvent(QStringLiteral("support_verified_result"),
                         {{QStringLiteral("result"), QStringLiteral("success")}});
                emit supportVerified();
                dialog->finish(QStringLiteral("verified"));
                return;
            }

            m_state = State::SupportFailed;
            QString message;
            if (status == QStringLiteral("expired"))
                message = QStringLiteral("支持会话已过期，请重新点击“去买咖啡”。");
            else if (status == QStringLiteral("rejected"))
                message = QStringLiteral("收款方暂未确认收到款，请检查是否已支付成功；如有疑问可发邮件联系。");
            else
                message = QStringLiteral("收款方还在确认中，稍等片刻再点“我已完成支持”试试。");
            dialog->setStatus(message, true);
            logEvent(QStringLiteral("support_verified_result"),
                     {{QStringLiteral("result"), QStringLiteral("failed")},
                      {QStringLiteral("status"), status},
                      {QStringLiteral("errorCode"), errorCode}});
        });
}

void SupportPrompt::loadSessionQr(const QUrl &qrUrl)
{
    const QPointer<SupportPromptDialog> dialog = m_dialog;
    if (!dialog)
        return;

    if (!qrUrl.isEmpty() && m_client) {
        m_client->fetchImage(qrUrl, [this, dialog](bool ok, const QImage &image,
                                                   const QString &) {
            if (!dialog)
                return;
            if (ok && !image.isNull())
                dialog->setQrImage(image);
            else
                applyStaticQr(m_session.checkoutUrl);
        });
        return;
    }

    applyStaticQr(m_session.checkoutUrl);
}

void SupportPrompt::applyFallbackCheckout()
{
    const QPointer<SupportPromptDialog> dialog = m_dialog;
    if (!dialog)
        return;

    if (m_config.fallbackCheckoutUrl.isEmpty()) {
        dialog->setStatus(QStringLiteral("未能连接校验服务，请稍后重试。"), true);
        return;
    }

    applyStaticQr(m_config.fallbackCheckoutUrl);
    QDesktopServices::openUrl(m_config.fallbackCheckoutUrl);
    dialog->setStatus(
        QStringLiteral("未能连接校验服务，可先通过链接支持；自动确认暂不可用。"),
        true);
}

void SupportPrompt::applyStaticQr(const QUrl &url)
{
    const QPointer<SupportPromptDialog> dialog = m_dialog;
    if (!dialog)
        return;

    if (m_qrProvider && !url.isEmpty()) {
        const QImage image = m_qrProvider(url.toString());
        if (!image.isNull()) {
            dialog->setQrImage(image);
            return;
        }
    }

    if (!m_config.fallbackQrImagePath.isEmpty()) {
        const QImage image(m_config.fallbackQrImagePath);
        if (!image.isNull()) {
            dialog->setQrImage(image);
            return;
        }
    }

    dialog->setQrPlaceholder(
        url.isEmpty() ? QStringLiteral("二维码将在创建支持会话后显示")
                      : QStringLiteral("二维码暂不可用，请使用下方链接"));
}

void SupportPrompt::setSuppressed(bool value, const QString &reason)
{
    if (!m_store)
        return;

    const bool previous = m_store->suppressed();
    m_store->setSuppressed(value);
    m_store->setSuppressedReason(value ? reason : QString());
    if (value && reason == QStringLiteral("verified"))
        m_store->setSupportVerified(true);

    if (previous == value)
        return;

    logEvent(QStringLiteral("suppressed_set"),
             {{QStringLiteral("suppressed"), value},
              {QStringLiteral("reason"), reason}});
    emit suppressedChanged(value, reason);
}

void SupportPrompt::logEvent(const QString &name, const QVariantMap &payload)
{
    QVariantMap enriched = payload;
    enriched.insert(QStringLiteral("timestamp"),
                    QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
    if (!m_config.appId.isEmpty())
        enriched.insert(QStringLiteral("appId"), m_config.appId);
    enriched.insert(QStringLiteral("platform"), platformName());

    if (m_config.debugLogging)
        qDebug().noquote() << "[SupportPrompt]" << name << enriched;

    emit eventLogged(name, enriched);
}

bool SupportPrompt::sessionValid() const
{
    if (m_session.id.isEmpty() || m_session.checkoutUrl.isEmpty())
        return false;
    if (m_session.expiresAt.isValid()
        && m_session.expiresAt <= QDateTime::currentDateTimeUtc()) {
        return false;
    }
    return true;
}

QString SupportPrompt::platformName() const
{
    return QSysInfo::prettyProductName();
}

void SupportPrompt::teardown()
{
    if (m_dialog) {
        SupportPromptDialog *dialog = m_dialog.data();
        m_dialog = nullptr;
        dialog->disconnect(this);
        dialog->hide();
        delete dialog;
    }

    delete m_client;
    m_client = nullptr;

    delete m_catalog;
    m_catalog = nullptr;

    delete m_store;
    m_store = nullptr;

    m_policy.reset();
    m_session = SessionInfo{};
    m_state = State::Idle;
    m_initialized = false;
}

} // namespace SupportPrompt
