#pragma once

#include <supportprompt/supportpromptconfig.h>

#include <QDialog>
#include <QImage>
#include <QUrl>

class QEvent;
class QLabel;
class QPushButton;

namespace SupportPrompt {

class SupportPromptDialog : public QDialog
{
    Q_OBJECT

public:
    explicit SupportPromptDialog(QWidget *parent = nullptr,
                                 const QString &iconPath = QString());

    void setPromptContent(const PromptText &text, int successCount, bool lastShow);
    void setContactEmail(const QString &email, const QString &subject);
    void setNeverRemindVisible(bool visible);
    void setBackendAvailable(bool available);
    void setQrImage(const QImage &image);
    void setQrPlaceholder(const QString &text);
    void setBusy(bool busy, const QString &status = QString());
    void setStatus(const QString &text, bool error);

    // 由模块主动结束弹窗（reason 会通过 dismissed 传给模块）
    void finish(const QString &reason);

    void reject() override;

protected:
    // 窗口尺寸/布局变化时同步最小高度，防止换行正文被垂直截断
    bool event(QEvent *event) override;

signals:
    void dismissed(const QString &reason);
    void buttonClicked(const QString &name);
    void supportClicked();
    void verifyClicked();

private:
    void buildUi();
    void closeWithReason(const QString &reason);
    void updateButtons();
    QUrl mailtoUrl() const;

    QLabel *m_titleIconLabel = nullptr;
    QLabel *m_titleLabel = nullptr;
    QLabel *m_subtitleLabel = nullptr;
    QLabel *m_bodyLabel = nullptr;
    QLabel *m_qrLabel = nullptr;
    QLabel *m_qrLabelRight = nullptr;
    QLabel *m_qrCaption = nullptr;
    QLabel *m_emailLabel = nullptr;
    QLabel *m_statusLabel = nullptr;
    QLabel *m_noteLabel = nullptr;
    QPushButton *m_copyEmailBtn = nullptr;
    QPushButton *m_mailBtn = nullptr;
    QPushButton *m_laterBtn = nullptr;
    QPushButton *m_neverBtn = nullptr;
    QPushButton *m_supportBtn = nullptr;
    QPushButton *m_verifyBtn = nullptr;

    QString m_closeReason = QStringLiteral("closed");
    QString m_contactEmail;
    QString m_contactEmailSubject;
    QString m_iconPath;
    bool m_backendAvailable = true;
    bool m_busy = false;
    bool m_neverVisible = true;
};

} // namespace SupportPrompt
