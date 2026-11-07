#pragma once

#include <QString>
#include <QUrl>
#include <QVector>

namespace SupportPrompt {

// 单条弹窗文案
struct PromptText
{
    QString title;
    QString body;
};

// 宿主传入的初始化配置。所有网络/文案行为均可配置，模块自身不做产品假设。
struct Config
{
    // 必填：后端用于区分调用方（宿主应用）的标识
    QString appId;

    // 支付校验后端根地址，例如 http://127.0.0.1:8787 或 https://api.example.com。
    // 为空时模块进入“离线模式”：只展示静态链接/二维码，无法自动确认赞助。
    QUrl apiBaseUrl;

    // 当前仅实现中文，保留字段便于后续扩展
    QString language = QStringLiteral("zh");

    // ---- 本地持久化 ----
    // 为空时使用系统默认的 QSettings 位置（需宿主设置 organizationName/applicationName）
    QString organization;
    QString application;
    QString settingsFilePath;                          // 非空时使用该 INI 文件
    QString storageGroup = QStringLiteral("SupportPrompt"); // QSettings 分组，避免污染宿主配置

    // ---- 触发策略 ----
    // 为空时使用 defaultTriggerIndices()（1,2,3,6,7,10,13,16,19,22,25,28,30,33,36,38,40）
    QVector<int> triggerIndices;
    int hardStopCount = 40;                            // 达到该次数展示最后一次，之后不再提示
    bool allowNeverRemind = true;                      // 是否展示“不再提醒”按钮
    // 点“不再提醒”后跳过多少次成功再恢复提醒（不是永久关闭）
    int neverRemindSkipCount = 5;

    // ---- 联系邮箱 ----
    QString contactEmail;                              // 必填：评价/反馈邮箱
    QString contactEmailSubject = QStringLiteral("关于使用体验的反馈");

    // ---- 离线兜底 ----
    // 后端不可用或尚未创建会话时展示的链接/二维码
    QUrl fallbackCheckoutUrl;
    QString fallbackQrImagePath;                       // 支持 ":/resources/xxx.png" 或本地绝对路径
    QString iconPath;                                  // 窗口/标题图标，空则用内置咖啡杯

    // ---- 文案 ----
    // 空则使用内置资源 :/supportprompt/prompts_zh.json
    QString promptsFilePath;

    // ---- 网络 ----
    int httpTimeoutMs = 8000;

    // 打开后会把关键事件输出到 qDebug，便于宿主联调
    bool debugLogging = false;

    bool isValid(QString *error = nullptr) const;
};

// 默认提醒序号：前期轻、中期加、后期密但不轰炸
QVector<int> defaultTriggerIndices();

// 每次“处理成功”时由宿主传入的上下文（可选，用于埋点）
struct Context
{
    QString appVersion;
    QString platform;
    QString lastProcessedFileType;
};

} // namespace SupportPrompt
