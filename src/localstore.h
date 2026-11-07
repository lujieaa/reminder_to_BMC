#pragma once

#include <supportprompt/supportpromptconfig.h>

#include <QDateTime>
#include <QString>

#include <memory>

class QSettings;

namespace SupportPrompt {

// 本地状态持久化（QSettings / INI）。
// suppressed 是“是否还应继续提示”的唯一真值。
class LocalStore
{
public:
    explicit LocalStore(const Config &config);
    ~LocalStore();

    int successCount() const;
    void setSuccessCount(int value);

    bool suppressed() const;
    void setSuppressed(bool value);

    int suppressUntilCount() const;
    void setSuppressUntilCount(int value);

    QString suppressedReason() const;
    void setSuppressedReason(const QString &reason);

    bool supportVerified() const;
    void setSupportVerified(bool value);

    int promptShownCount() const;
    void setPromptShownCount(int value);

    QString lastPromptAt() const;
    void setLastPromptAt(const QDateTime &when);

    QString lastSupportSessionId() const;
    void setLastSupportSessionId(const QString &sessionId);

    void reset();

private:
    QString key(const QString &name) const;

    std::unique_ptr<QSettings> m_settings;
    QString m_group;
};

} // namespace SupportPrompt
