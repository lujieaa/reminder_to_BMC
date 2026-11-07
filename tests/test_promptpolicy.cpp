#include <supportprompt/promptpolicy.h>

#include <cassert>
#include <iostream>
#include <vector>

using SupportPrompt::PromptPolicy;

namespace {

std::vector<int> defaultTriggers()
{
    return {1, 2, 3, 6, 7, 10, 13, 16, 19, 22, 25, 28, 30, 33, 36, 38, 40};
}

std::vector<int> shownIndices(const PromptPolicy &policy, int from, int to,
                              int suppressUntil = 0)
{
    std::vector<int> shown;
    for (int count = from; count <= to; ++count) {
        if (policy.evaluate(count, false, suppressUntil) != PromptPolicy::Decision::None)
            shown.push_back(count);
    }
    return shown;
}

} // namespace

int main()
{
    const std::vector<int> triggers = defaultTriggers();
    const PromptPolicy policy(triggers, 40);

    // 1..40 只应在触发点展示，40 为最后一次
    assert(shownIndices(policy, 1, 40) == triggers);
    for (int count = 1; count <= 40; ++count) {
        const auto decision = policy.evaluate(count, false);
        assert((decision == PromptPolicy::Decision::LastShow) == (count == 40));
    }

    // suppressed 后永不展示
    for (int count = 1; count <= 40; ++count)
        assert(policy.evaluate(count, true) == PromptPolicy::Decision::None);

    // 超过 40 次后不再提示
    assert(policy.evaluate(41, false) == PromptPolicy::Decision::None);
    assert(policy.evaluate(100, false) == PromptPolicy::Decision::None);

    // 自定义 hardStop（且该次数在触发列表内）
    const PromptPolicy custom({5, 10}, 10);
    assert(custom.evaluate(5, false) == PromptPolicy::Decision::Show);
    assert(custom.evaluate(10, false) == PromptPolicy::Decision::LastShow);
    assert(custom.evaluate(11, false) == PromptPolicy::Decision::None);

    // 乱序 / 重复的触发列表会被排序去重
    const PromptPolicy messy({3, 1, 1, 2}, 40);
    assert(messy.triggers().size() == 3);
    assert(messy.evaluate(1, false) == PromptPolicy::Decision::Show);
    assert(messy.evaluate(2, false) == PromptPolicy::Decision::Show);
    assert(messy.evaluate(3, false) == PromptPolicy::Decision::Show);
    assert(messy.evaluate(4, false) == PromptPolicy::Decision::None);

    // “不再提醒”间隔抑制：suppressUntilCount=10 时，1..9 都不展示，10 起恢复
    const std::vector<int> afterSkip = shownIndices(policy, 1, 40, 10);
    for (int count : afterSkip)
        assert(count >= 10);
    // 10 是触发点且 >= suppressUntil，应展示
    assert(policy.evaluate(10, false, 10) == PromptPolicy::Decision::Show);
    // 6 < 10，应被跳过
    assert(policy.evaluate(6, false, 10) == PromptPolicy::Decision::None);

    std::cout << "all prompt policy tests passed\n";
    return 0;
}
