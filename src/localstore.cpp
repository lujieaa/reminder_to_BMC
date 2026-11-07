#include "localstore.h"

#include <QSettings>

namespace SupportPrompt {

LocalStore::LocalStore(const Config &config)
    : m_group(config.storageGroup.trimmed().isEmpty()
                  ? QStringLiteral("SupportPrompt")
                  : config.storageGroup.trimmed())
{
    if (!config.settingsFilePath.isEmpty()) {
        m_settings.reset(new QSettings(config.settingsFilePath, QSettings::IniFormat));
    } else {
        const QString organization = config.organization.isEmpty()
            ? QStringLiteral("SupportPrompt")
            : config.organization;
        const QString application = config.application.isEmpty()
            ? config.appId
            : config.application;
        m_settings.reset(new QSettings(QSettings::IniFormat, QSettings::UserScope,
                                      organization, application));
    }
}

LocalStore::~LocalStore() = default;

QString LocalStore::key(const QString &name) const
{
    return m_group + QLatin1Char('/') + name;
}

int LocalStore::successCount() const
{
    return m_settings->value(key(QStringLiteral("successCount")), 0).toInt();
}

void LocalStore::setSuccessCount(int value)
{
    m_settings->setValue(key(QStringLiteral("successCount")), qMax(0, value));
    m_settings->sync();
}

bool LocalStore::suppressed() const
{
    return m_settings->value(key(QStringLiteral("suppressed")), false).toBool();
}

void LocalStore::setSuppressed(bool value)
{
    m_settings->setValue(key(QStringLiteral("suppressed")), value);
    m_settings->sync();
}

int LocalStore::suppressUntilCount() const
{
    return m_settings->value(key(QStringLiteral("suppressUntilCount")), 0).toInt();
}

void LocalStore::setSuppressUntilCount(int value)
{
    m_settings->setValue(key(QStringLiteral("suppressUntilCount")), qMax(0, value));
    m_settings->sync();
}

QString LocalStore::suppressedReason() const
{
    return m_settings->value(key(QStringLiteral("suppressedReason"))).toString();
}

void LocalStore::setSuppressedReason(const QString &reason)
{
    m_settings->setValue(key(QStringLiteral("suppressedReason")), reason);
    m_settings->sync();
}

bool LocalStore::supportVerified() const
{
    return m_settings->value(key(QStringLiteral("supportVerified")), false).toBool();
}

void LocalStore::setSupportVerified(bool value)
{
    m_settings->setValue(key(QStringLiteral("supportVerified")), value);
    m_settings->sync();
}

int LocalStore::promptShownCount() const
{
    return m_settings->value(key(QStringLiteral("promptShownCount")), 0).toInt();
}

void LocalStore::setPromptShownCount(int value)
{
    m_settings->setValue(key(QStringLiteral("promptShownCount")), qMax(0, value));
    m_settings->sync();
}

QString LocalStore::lastPromptAt() const
{
    return m_settings->value(key(QStringLiteral("lastPromptAt"))).toString();
}

void LocalStore::setLastPromptAt(const QDateTime &when)
{
    m_settings->setValue(key(QStringLiteral("lastPromptAt")),
                        when.toUTC().toString(Qt::ISODate));
    m_settings->sync();
}

QString LocalStore::lastSupportSessionId() const
{
    return m_settings->value(key(QStringLiteral("lastSupportSessionId"))).toString();
}

void LocalStore::setLastSupportSessionId(const QString &sessionId)
{
    m_settings->setValue(key(QStringLiteral("lastSupportSessionId")), sessionId);
    m_settings->sync();
}

void LocalStore::reset()
{
    m_settings->remove(m_group);
    m_settings->sync();
}

} // namespace SupportPrompt
