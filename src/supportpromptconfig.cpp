#include <supportprompt/supportpromptconfig.h>

#include <QFileInfo>

namespace SupportPrompt {

QVector<int> defaultTriggerIndices()
{
    return {1, 2, 3, 6, 7, 10, 13, 16, 19, 22, 25, 28, 30, 33, 36, 38, 40};
}

bool Config::isValid(QString *error) const
{
    auto fail = [error](const QString &message) {
        if (error)
            *error = message;
        return false;
    };

    if (appId.trimmed().isEmpty())
        return fail(QStringLiteral("appId 不能为空"));

    if (contactEmail.trimmed().isEmpty())
        return fail(QStringLiteral("contactEmail 不能为空"));

    if (hardStopCount <= 0)
        return fail(QStringLiteral("hardStopCount 必须大于 0"));

    if (neverRemindSkipCount < 0)
        return fail(QStringLiteral("neverRemindSkipCount 不能为负数"));

    if (!apiBaseUrl.isEmpty()) {
        if (!apiBaseUrl.isValid()
            || (apiBaseUrl.scheme() != QStringLiteral("http")
                && apiBaseUrl.scheme() != QStringLiteral("https"))) {
            return fail(QStringLiteral("apiBaseUrl 必须是有效的 http/https 地址"));
        }
    }

    if (!settingsFilePath.isEmpty()) {
        const QFileInfo info(settingsFilePath);
        if (!info.absoluteDir().exists())
            return fail(QStringLiteral("settingsFilePath 所在目录不存在"));
    }

    if (error)
        error->clear();
    return true;
}

} // namespace SupportPrompt
