#pragma once

#include <vector>

namespace SupportPrompt {

// 纯 C++ 触发策略：不依赖 Qt，便于单元测试。
// 规则：
//   - suppressed=true 时永不展示（赞助已验证，永久关闭）
//   - suppressUntilCount>0 且 successCount<suppressUntilCount 时不展示
//     （用户点了“不再提醒”，跳过若干次后恢复）
//   - successCount 命中 triggerIndices 时展示
//   - successCount == hardStopCount 的那次标记为“最后一次提醒”
//   - successCount > hardStopCount 后永不展示（无论是否赞助）
class PromptPolicy
{
public:
    enum class Decision {
        None,
        Show,
        LastShow
    };

    PromptPolicy() = default;
    PromptPolicy(std::vector<int> triggers, int hardStopCount);

    Decision evaluate(int successCount, bool suppressed,
                      int suppressUntilCount = 0) const;
    bool isTrigger(int successCount) const;
    bool isPastHardStop(int successCount) const;

    const std::vector<int> &triggers() const { return m_triggers; }
    int hardStopCount() const { return m_hardStopCount; }

private:
    std::vector<int> m_triggers;
    int m_hardStopCount = 40;
};

} // namespace SupportPrompt
