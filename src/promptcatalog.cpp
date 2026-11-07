#include "promptcatalog.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>

namespace SupportPrompt {

bool PromptCatalog::load(const QString &path, QString *error)
{
    const QString target = path.isEmpty()
        ? QStringLiteral(":/supportprompt/prompts_zh.json")
        : path;

    QFile file(target);
    if (!file.open(QIODevice::ReadOnly)) {
        if (error)
            *error = QStringLiteral("无法打开文案文件：%1").arg(target);
        return false;
    }

    QJsonParseError parseError{};
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        if (error) {
            *error = QStringLiteral("文案 JSON 解析失败：%1（偏移 %2）")
                         .arg(parseError.errorString())
                         .arg(parseError.offset);
        }
        return false;
    }

    const QJsonArray prompts = document.object().value(QStringLiteral("prompts")).toArray();
    m_texts.clear();

    for (const QJsonValue &value : prompts) {
        if (!value.isObject())
            continue;
        const QJsonObject item = value.toObject();
        const int trigger = item.value(QStringLiteral("trigger")).toInt();
        const QString body = item.value(QStringLiteral("body")).toString();
        if (trigger <= 0 || body.trimmed().isEmpty())
            continue;

        PromptText text;
        text.title = item.value(QStringLiteral("title")).toString();
        text.body = body;
        m_texts.insert(trigger, text);
    }

    if (m_texts.isEmpty()) {
        if (error)
            *error = QStringLiteral("文案文件中没有有效条目：%1").arg(target);
        return false;
    }

    if (error)
        error->clear();
    return true;
}

PromptText PromptCatalog::textFor(int triggerIndex) const
{
    return m_texts.value(triggerIndex, fallbackFor(triggerIndex));
}

PromptText PromptCatalog::fallbackFor(int triggerIndex)
{
    PromptText text;
    text.title = QStringLiteral("可以请我喝杯咖啡吗？");
    text.body = QStringLiteral(
                    "第 %1 次处理成功！感谢你的信任。可以请我喝杯咖啡支持一下吗？"
                    "只买一次就好——以后不会再用这件事打扰你。")
                    .arg(triggerIndex);
    return text;
}

} // namespace SupportPrompt
