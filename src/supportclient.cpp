#include "supportclient.h"

#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QNetworkReply>
#include <QSysInfo>
#include <QUrlQuery>

namespace SupportPrompt {

namespace {

QDateTime parseIsoDateTime(const QString &value)
{
    if (value.isEmpty())
        return {};

    QDateTime dateTime = QDateTime::fromString(value, Qt::ISODateWithMs);
    if (!dateTime.isValid())
        dateTime = QDateTime::fromString(value, Qt::ISODate);
    if (dateTime.isValid() && dateTime.timeSpec() == Qt::LocalTime)
        dateTime.setTimeSpec(Qt::UTC);
    return dateTime;
}

struct ResponsePayload
{
    bool ok = false;
    int httpStatus = 0;
    int code = 0;
    QString message;
    QJsonObject data;
};

ResponsePayload parseResponse(QNetworkReply *reply)
{
    ResponsePayload payload;
    payload.httpStatus = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    const QByteArray body = reply->readAll();

    QJsonParseError parseError{};
    const QJsonDocument document = QJsonDocument::fromJson(body, &parseError);
    QJsonObject root;
    if (parseError.error == QJsonParseError::NoError && document.isObject())
        root = document.object();

    if (root.contains(QStringLiteral("code")))
        payload.code = root.value(QStringLiteral("code")).toInt();
    payload.message = root.value(QStringLiteral("msg")).toString();

    const QJsonObject data = root.value(QStringLiteral("data")).toObject();
    payload.data = data.isEmpty() ? root : data;

    const bool networkOk = reply->error() == QNetworkReply::NoError;
    const bool httpOk = payload.httpStatus == 0 || payload.httpStatus < 400;
    const bool businessOk = payload.code == 0;

    if (!networkOk || !httpOk || !businessOk) {
        if (payload.message.isEmpty()) {
            payload.message = networkOk
                ? QStringLiteral("HTTP %1").arg(payload.httpStatus)
                : reply->errorString();
        }
        return payload;
    }

    payload.ok = true;
    return payload;
}

} // namespace

bool SupportSession::isValid() const
{
    if (id.isEmpty() || checkoutUrl.isEmpty() || !checkoutUrl.isValid())
        return false;
    if (!expiresAt.isValid())
        return true;
    return expiresAt > QDateTime::currentDateTimeUtc();
}

SupportClient::SupportClient(const Config &config, QObject *parent)
    : QObject(parent)
    , m_config(config)
    , m_network(new QNetworkAccessManager(this))
{
}

QUrl SupportClient::endpoint(const QString &path) const
{
    QUrl url = m_config.apiBaseUrl;
    QString basePath = url.path();
    while (basePath.endsWith(QLatin1Char('/')))
        basePath.chop(1);
    url.setPath(basePath + path);
    url.setQuery(QString());
    url.setFragment(QString());
    return url;
}

void SupportClient::applyTimeout(QNetworkRequest &request) const
{
#if QT_VERSION >= QT_VERSION_CHECK(5, 15, 0)
    request.setTransferTimeout(m_config.httpTimeoutMs);
#else
    Q_UNUSED(request)
#endif
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);
}

void SupportClient::createSession(const QString &promptKey, int successCount,
                                  SessionCallback callback)
{
    QJsonObject payload;
    payload.insert(QStringLiteral("appId"), m_config.appId);
    payload.insert(QStringLiteral("platform"), QSysInfo::prettyProductName());
    payload.insert(QStringLiteral("language"), m_config.language);
    payload.insert(QStringLiteral("promptKey"), promptKey);
    payload.insert(QStringLiteral("successCount"), successCount);
    payload.insert(QStringLiteral("timestamp"),
                   QDateTime::currentDateTimeUtc().toString(Qt::ISODate));

    QNetworkRequest request(endpoint(QStringLiteral("/support/session/create")));
    request.setHeader(QNetworkRequest::ContentTypeHeader,
                      QStringLiteral("application/json; charset=utf-8"));
    applyTimeout(request);

    QNetworkReply *reply =
        m_network->post(request, QJsonDocument(payload).toJson(QJsonDocument::Compact));

    QObject::connect(reply, &QNetworkReply::finished, reply, [this, reply, callback]() {
        const ResponsePayload response = parseResponse(reply);
        reply->deleteLater();
        if (!response.ok) {
            callback(false, SupportSession{}, response.message);
            return;
        }

        SupportSession session;
        session.id = response.data.value(QStringLiteral("supportSessionId")).toString();
        session.checkoutUrl =
            QUrl(response.data.value(QStringLiteral("coffeeCheckoutUrl")).toString());
        session.qrPngUrl =
            QUrl(response.data.value(QStringLiteral("qrPngUrl")).toString());
        session.expiresAt =
            parseIsoDateTime(response.data.value(QStringLiteral("expiresAt")).toString());

        if (session.checkoutUrl.isRelative())
            session.checkoutUrl = m_config.apiBaseUrl.resolved(session.checkoutUrl);
        if (session.qrPngUrl.isRelative())
            session.qrPngUrl = m_config.apiBaseUrl.resolved(session.qrPngUrl);

        if (session.id.isEmpty() || session.checkoutUrl.isEmpty()
            || !session.checkoutUrl.isValid()) {
            callback(false, SupportSession{}, QStringLiteral("服务器返回的会话数据不完整"));
            return;
        }

        callback(true, session, QString());
    });
}

void SupportClient::verify(const QString &sessionId, VerifyCallback callback)
{
    QUrl url = endpoint(QStringLiteral("/support/verify"));
    QUrlQuery query;
    query.addQueryItem(QStringLiteral("sid"), sessionId);
    url.setQuery(query);

    QNetworkRequest request(url);
    applyTimeout(request);

    QNetworkReply *reply = m_network->get(request);
    QObject::connect(reply, &QNetworkReply::finished, reply, [reply, callback]() {
        const ResponsePayload response = parseResponse(reply);
        reply->deleteLater();
        if (!response.ok) {
            callback(false, false, QString(), response.message,
                     QString::number(response.code));
            return;
        }

        const bool verified =
            response.data.value(QStringLiteral("verified")).toBool(false);
        const QString status = response.data.value(QStringLiteral("status")).toString();
        const QString errorCode =
            response.data.value(QStringLiteral("errorCode")).toString();

        callback(true, verified, status, QString(), errorCode);
    });
}

void SupportClient::fetchImage(const QUrl &url, ImageCallback callback)
{
    if (url.isEmpty() || !url.isValid()) {
        callback(false, QImage{}, QStringLiteral("二维码地址无效"));
        return;
    }

    QNetworkRequest request(url);
    applyTimeout(request);

    QNetworkReply *reply = m_network->get(request);
    QObject::connect(reply, &QNetworkReply::finished, reply, [reply, callback]() {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) {
            callback(false, QImage{}, reply->errorString());
            return;
        }

        const QByteArray data = reply->readAll();
        if (data.isEmpty() || data.size() > 4 * 1024 * 1024) {
            callback(false, QImage{}, QStringLiteral("二维码图片为空或过大"));
            return;
        }

        QImage image;
        if (!image.loadFromData(data)) {
            callback(false, QImage{}, QStringLiteral("二维码图片解析失败"));
            return;
        }

        callback(true, image, QString());
    });
}

} // namespace SupportPrompt
