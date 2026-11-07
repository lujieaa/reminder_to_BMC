#pragma once

#include <supportprompt/supportpromptconfig.h>

#include <QMap>

namespace SupportPrompt {

// 从 JSON 加载每个触发序号对应的文案；加载失败时回落到通用文案。
class PromptCatalog
{
public:
    bool load(const QString &path, QString *error = nullptr);
    PromptText textFor(int triggerIndex) const;

    static PromptText fallbackFor(int triggerIndex);

private:
    QMap<int, PromptText> m_texts;
};

} // namespace SupportPrompt
