#pragma once

#include <supportprompt/supportpromptconfig.h>

#include <QDateTime>
#include <QImage>
#include <QNetworkAccessManager>
#include <QNetworkRequest>
#include <QObject>
#include <QUrl>

#include <functional>

namespace SupportPrompt {

struct SupportSession
{
    QString id;
    QUrl checkoutUrl;
    QUrl qrPngUrl;
    QDateTime expiresAt;

    bool isValid() const;
};

// 后端接口契约（详见 README/integration 注释）：
//
// 1) POST /support/session/create
//    请求：{ appId, platform, language, promptKey, successCount, timestamp }
//    响应：{ "code": 0, "data": {
//              "supportSessionId": "...",
//              "coffeeCheckoutUrl": "https://...",
//              "qrPngUrl": "https://...",          // 可选，二维码图片
//              "expiresAt": "2026-10-27T12:00:00Z" // 可选
//           }}
//    错误：{ "code": 1001, "msg": "invalid_request" }
//
// 2) GET /support/verify?sid=...
//    响应：{ "code": 0, "data": { "verified": true, "status": "paid" } }
//    status 取值：paid / pending / not_found / expired
//
// 3) GET qrPngUrl（可选）：二维码 PNG 图片
//
// 错误码约定（客户端只负责展示 msg，不硬编码业务分支）：
//   1001 invalid_request
//   1002 session_not_found
//   1003 session_expired
//   2001 payment_pending
//   5000 server_error
class SupportClient : public QObject
{
    Q_OBJECT

public:
    using SessionCallback =
        std::function<void(bool ok, const SupportSession &session, const QString &error)>;
    using VerifyCallback =
        std::function<void(bool ok, bool verified, const QString &status,
                           const QString &error, const QString &errorCode)>;
    using ImageCallback =
        std::function<void(bool ok, const QImage &image, const QString &error)>;

    explicit SupportClient(const Config &config, QObject *parent = nullptr);

    void createSession(const QString &promptKey, int successCount, SessionCallback callback);
    void verify(const QString &sessionId, VerifyCallback callback);
    void fetchImage(const QUrl &url, ImageCallback callback);

private:
    QUrl endpoint(const QString &path) const;
    void applyTimeout(QNetworkRequest &request) const;

    Config m_config;
    QNetworkAccessManager *m_network;
};

} // namespace SupportPrompt
