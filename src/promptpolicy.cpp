#include <supportprompt/promptpolicy.h>

#include <algorithm>
#include <utility>

namespace SupportPrompt {

PromptPolicy::PromptPolicy(std::vector<int> triggers, int hardStopCount)
    : m_triggers(std::move(triggers))
    , m_hardStopCount(hardStopCount > 0 ? hardStopCount : 40)
{
    std::sort(m_triggers.begin(), m_triggers.end());
    m_triggers.erase(std::unique(m_triggers.begin(), m_triggers.end()), m_triggers.end());
}

PromptPolicy::Decision PromptPolicy::evaluate(int successCount, bool suppressed,
                                              int suppressUntilCount) const
{
    if (suppressed)
        return Decision::None;
    if (successCount <= 0)
        return Decision::None;
    if (isPastHardStop(successCount))
        return Decision::None;
    if (suppressUntilCount > 0 && successCount < suppressUntilCount)
        return Decision::None;
    if (!isTrigger(successCount))
        return Decision::None;

    return successCount == m_hardStopCount ? Decision::LastShow : Decision::Show;
}

bool PromptPolicy::isTrigger(int successCount) const
{
    return std::binary_search(m_triggers.begin(), m_triggers.end(), successCount);
}

bool PromptPolicy::isPastHardStop(int successCount) const
{
    return successCount > m_hardStopCount;
}

} // namespace SupportPrompt
