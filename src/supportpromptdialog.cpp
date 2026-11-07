#include "supportpromptdialog.h"

#include <QApplication>
#include <QClipboard>
#include <QColor>
#include <QDesktopServices>
#include <QEvent>
#include <QFrame>
#include <QHBoxLayout>
#include <QIcon>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QSizePolicy>
#include <QUrlQuery>
#include <QVBoxLayout>

namespace {

// 让自动换行的 QLabel 参与 heightForWidth 布局：QLabel 默认 sizePolicy
// 不带 heightForWidth 标志，换行后的实际高度不会反馈给布局
void enableHeightForWidth(QLabel *label)
{
    QSizePolicy policy = label->sizePolicy();
    policy.setHeightForWidth(true);
    label->setSizePolicy(policy);
}

// 码位 QLabel 为 260x293，去掉 padding/border 后内容区约 238x269
constexpr int kQrFitW = 238;
constexpr int kQrFitH = 269;

QPixmap fitQr(const QImage &image)
{
    return QPixmap::fromImage(image).scaled(
        kQrFitW, kQrFitH, Qt::KeepAspectRatio, Qt::SmoothTransformation);
}

// 裁掉纯色边距，只留白色卡片区域（二维码印在白卡上）。
// 在缩略图上定位“近白色像素覆盖率足够高”的行（卡片主体），
// 避免白色标题文字把包围盒撑到卡片之外；只扫描上部 80%。
QImage cropToCard(const QImage &image)
{
    const QImage small = image.scaledToWidth(160, Qt::SmoothTransformation)
                             .convertToFormat(QImage::Format_RGB32);
    const int sw = small.width();
    const int sh = small.height();
    const int scanH = qMax(1, int(sh * 0.8));
    const int threshold = int(sw * 0.4);

    auto isWhite = [&small](int x, int y) {
        const QColor c = small.pixelColor(x, y);
        return c.red() > 238 && c.green() > 238 && c.blue() > 238;
    };

    int y0 = -1, y1 = -1;
    for (int y = 0; y < scanH; ++y) {
        int count = 0;
        for (int x = 0; x < sw; ++x)
            if (isWhite(x, y))
                ++count;
        if (count > threshold) {
            if (y0 < 0)
                y0 = y;
            y1 = y;
        }
    }
    if (y0 < 0 || (y1 - y0) < int(scanH * 0.2))
        return image;  // 没找到明显卡片，原样返回

    int x0 = sw, x1 = -1;
    for (int y = y0; y <= y1; ++y)
        for (int x = 0; x < sw; ++x)
            if (isWhite(x, y)) {
                x0 = qMin(x0, x);
                x1 = qMax(x1, x);
            }
    if (x1 < 0 || (x1 - x0) < int(sw * 0.2))
        return image;

    const double scale = double(image.width()) / sw;
    const int margin = int(image.width() * 0.03);
    const int left = qMax(0, int(x0 * scale) - margin);
    const int top = qMax(0, int(y0 * scale) - margin);
    const int right = qMin(image.width(), int((x1 + 1) * scale) + margin);
    const int bottom = qMin(image.height(), int((y1 + 1) * scale) + margin);
    return image.copy(left, top, right - left, bottom - top);
}

} // namespace

namespace SupportPrompt {

SupportPromptDialog::SupportPromptDialog(QWidget *parent, const QString &iconPath)
    : QDialog(parent)
    , m_iconPath(iconPath)
{
    buildUi();
}

void SupportPromptDialog::buildUi()
{
    setWindowTitle(QStringLiteral("可以请我喝杯咖啡吗？"));
    setModal(false);
    setSizeGripEnabled(false);
    setWindowFlag(Qt::WindowContextHelpButtonHint, false);
    setAttribute(Qt::WA_StyledBackground, true);
    setMinimumWidth(600);

    if (!m_iconPath.isEmpty()) {
        const QIcon icon(m_iconPath);
        if (!icon.isNull())
            setWindowIcon(icon);
    }

    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(32, 24, 32, 22);
    root->setSpacing(14);

    // 标题行：讨喜的咖啡杯图标 + 标题
    auto *titleRow = new QHBoxLayout();
    titleRow->setSpacing(12);
    m_titleIconLabel = new QLabel(this);
    m_titleIconLabel->setFixedSize(44, 44);
    if (!m_iconPath.isEmpty()) {
        const QIcon icon(m_iconPath);
        if (!icon.isNull())
            m_titleIconLabel->setPixmap(icon.pixmap(40, 40));
    }
    m_titleLabel = new QLabel(this);
    m_titleLabel->setObjectName(QStringLiteral("titleLabel"));
    titleRow->addWidget(m_titleIconLabel);
    titleRow->addWidget(m_titleLabel, 1);
    titleRow->addStretch(1);

    m_subtitleLabel = new QLabel(this);
    m_subtitleLabel->setObjectName(QStringLiteral("subtitleLabel"));

    auto *separator = new QFrame(this);
    separator->setObjectName(QStringLiteral("separator"));
    separator->setFrameShape(QFrame::HLine);

    m_bodyLabel = new QLabel(this);
    m_bodyLabel->setObjectName(QStringLiteral("bodyLabel"));
    m_bodyLabel->setWordWrap(true);
    m_bodyLabel->setTextFormat(Qt::PlainText);
    m_bodyLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    enableHeightForWidth(m_bodyLabel);

    auto *emailRow = new QHBoxLayout();
    emailRow->setSpacing(8);
    m_emailLabel = new QLabel(this);
    m_emailLabel->setObjectName(QStringLiteral("emailLabel"));
    m_emailLabel->setTextFormat(Qt::PlainText);
    m_emailLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    m_copyEmailBtn = new QPushButton(QStringLiteral("复制邮箱"), this);
    m_mailBtn = new QPushButton(QStringLiteral("写邮件"), this);
    emailRow->addWidget(m_emailLabel, 1);
    emailRow->addWidget(m_copyEmailBtn, 0);
    emailRow->addWidget(m_mailBtn, 0);

    // 二维码：双码（支付宝/微信）并排显示，单码会话二维码居中显示。
    // 单个码必须足够大才能被手机扫上，所以双码时拆成两个独立码位。
    m_qrLabel = new QLabel(this);
    m_qrLabel->setObjectName(QStringLiteral("qrLabel"));
    m_qrLabel->setFixedSize(260, 293);
    m_qrLabel->setAlignment(Qt::AlignCenter);
    m_qrLabel->setWordWrap(true);
    m_qrLabel->setText(QStringLiteral("点击“去买咖啡”后，在支付页面扫码"));
    m_qrLabel->hide();

    m_qrLabelRight = new QLabel(this);
    m_qrLabelRight->setObjectName(QStringLiteral("qrLabel"));
    m_qrLabelRight->setFixedSize(260, 293);
    m_qrLabelRight->setAlignment(Qt::AlignCenter);
    m_qrLabelRight->hide();

    m_qrCaption = new QLabel(QStringLiteral("扫码支持我一下 ♡"), this);
    m_qrCaption->setObjectName(QStringLiteral("qrCaption"));
    m_qrCaption->setAlignment(Qt::AlignCenter);
    m_qrCaption->hide();

    auto *qrRow = new QHBoxLayout();
    qrRow->setSpacing(12);
    qrRow->addStretch(1);
    qrRow->addWidget(m_qrLabel);
    qrRow->addWidget(m_qrLabelRight);
    qrRow->addStretch(1);

    auto *qrBox = new QVBoxLayout();
    qrBox->setSpacing(6);
    qrBox->addLayout(qrRow);
    qrBox->addWidget(m_qrCaption, 0, Qt::AlignHCenter);

    m_statusLabel = new QLabel(this);
    m_statusLabel->setObjectName(QStringLiteral("statusLabel"));
    m_statusLabel->setWordWrap(true);
    m_statusLabel->setVisible(false);
    enableHeightForWidth(m_statusLabel);

    m_noteLabel = new QLabel(
        QStringLiteral("支持完全自愿，不赞助也不影响任何功能。"), this);
    m_noteLabel->setObjectName(QStringLiteral("noteLabel"));
    m_noteLabel->setWordWrap(true);
    enableHeightForWidth(m_noteLabel);

    auto *buttonRow = new QHBoxLayout();
    buttonRow->setSpacing(8);
    m_laterBtn = new QPushButton(QStringLiteral("稍后再说"), this);
    m_neverBtn = new QPushButton(QStringLiteral("不再提醒"), this);
    m_supportBtn = new QPushButton(QStringLiteral("去买咖啡"), this);
    m_supportBtn->setObjectName(QStringLiteral("primaryButton"));
    m_verifyBtn = new QPushButton(QStringLiteral("我已完成支持"), this);
    m_verifyBtn->setObjectName(QStringLiteral("secondaryButton"));

    buttonRow->addWidget(m_laterBtn);
    buttonRow->addWidget(m_neverBtn);
    buttonRow->addStretch(1);
    buttonRow->addWidget(m_supportBtn);
    buttonRow->addWidget(m_verifyBtn);

    root->addLayout(titleRow);
    root->addWidget(m_subtitleLabel);
    root->addWidget(separator);
    root->addWidget(m_bodyLabel);
    root->addLayout(emailRow);
    root->addLayout(qrBox);
    root->addWidget(m_statusLabel);
    root->addWidget(m_noteLabel);
    root->addLayout(buttonRow);

    setStyleSheet(QStringLiteral(R"(
        QDialog { background-color: #FFFBF5; }
        QLabel#titleLabel { font-size: 22px; font-weight: 700; color: #4A2F1B; }
        QLabel#subtitleLabel { font-size: 12px; color: #A8896E; }
        QLabel#bodyLabel { font-size: 14px; color: #4A3526; }
        QLabel#emailLabel { font-size: 12px; color: #6E5744; }
        QLabel#qrCaption { font-size: 12px; color: #8A6F57; font-weight: 500; }
        QLabel#noteLabel { font-size: 11px; color: #A89380; }
        QLabel#statusLabel { font-size: 12px; color: #6E5744; }
        QLabel#qrLabel {
            background-color: #FFFFFF;
            border: 1px solid #F0E2D2;
            border-radius: 14px;
            color: #B5A494;
            font-size: 12px;
            padding: 10px;
        }
        QFrame#separator { color: #F2E4D4; }
        QPushButton {
            background-color: #F3E6D8;
            color: #5A3D27;
            border: none;
            border-radius: 8px;
            padding: 9px 16px;
            font-size: 13px;
        }
        QPushButton:hover { background-color: #E9D5BF; }
        QPushButton:pressed { background-color: #DEC7AE; }
        QPushButton:disabled { color: #B5A494; background-color: #F7EFE6; }
        QPushButton#primaryButton {
            background-color: #D18B4A;
            color: #FFFFFF;
            font-weight: 600;
        }
        QPushButton#primaryButton:hover { background-color: #C47A3C; }
        QPushButton#primaryButton:pressed { background-color: #B06A30; }
        QPushButton#primaryButton:disabled { background-color: #E3C4A8; color: #FFFFFF; }
        QPushButton#secondaryButton {
            background-color: #FFF3E6;
            color: #A85F2A;
            border: 1px solid #EBC9A6;
        }
        QPushButton#secondaryButton:hover { background-color: #FFE8CE; }
        QPushButton#secondaryButton:disabled { color: #C9B29C; border-color: #EADCCB; }
    )"));

    connect(m_laterBtn, &QPushButton::clicked, this, [this]() {
        emit buttonClicked(QStringLiteral("later"));
        closeWithReason(QStringLiteral("later"));
    });

    connect(m_neverBtn, &QPushButton::clicked, this, [this]() {
        emit buttonClicked(QStringLiteral("never"));
        closeWithReason(QStringLiteral("never"));
    });

    connect(m_supportBtn, &QPushButton::clicked, this, [this]() {
        emit buttonClicked(QStringLiteral("support"));
        emit supportClicked();
    });

    connect(m_verifyBtn, &QPushButton::clicked, this, [this]() {
        emit buttonClicked(QStringLiteral("verify"));
        emit verifyClicked();
    });

    connect(m_copyEmailBtn, &QPushButton::clicked, this, [this]() {
        QApplication::clipboard()->setText(m_contactEmail);
        setStatus(QStringLiteral("邮箱已复制到剪贴板。"), false);
        emit buttonClicked(QStringLiteral("copy_email"));
    });

    connect(m_mailBtn, &QPushButton::clicked, this, [this]() {
        QDesktopServices::openUrl(mailtoUrl());
        emit buttonClicked(QStringLiteral("mailto"));
    });

    updateButtons();
}

void SupportPromptDialog::setPromptContent(const PromptText &text, int successCount,
                                           bool lastShow)
{
    const QString title = text.title.trimmed().isEmpty()
        ? QStringLiteral("可以请我喝杯咖啡吗？")
        : text.title;
    m_titleLabel->setText(title);
    m_subtitleLabel->setText(
        lastShow
            ? QStringLiteral("第 %1 次处理成功 · 最后一次提醒").arg(successCount)
            : QStringLiteral("第 %1 次处理成功").arg(successCount));
    m_bodyLabel->setText(text.body);
}

void SupportPromptDialog::setContactEmail(const QString &email, const QString &subject)
{
    m_contactEmail = email.trimmed();
    m_contactEmailSubject = subject;
    m_emailLabel->setText(QStringLiteral("反馈 / 评价请发邮件到：%1").arg(m_contactEmail));
    const bool hasEmail = !m_contactEmail.isEmpty();
    m_emailLabel->setVisible(hasEmail);
    m_copyEmailBtn->setVisible(hasEmail);
    m_mailBtn->setVisible(hasEmail);
}

void SupportPromptDialog::setNeverRemindVisible(bool visible)
{
    m_neverVisible = visible;
    m_neverBtn->setVisible(visible);
}

void SupportPromptDialog::setBackendAvailable(bool available)
{
    m_backendAvailable = available;
    m_verifyBtn->setToolTip(
        available
            ? QString()
            : QStringLiteral("当前未配置校验服务，无法自动确认支持状态"));
    updateButtons();
}

void SupportPromptDialog::setQrImage(const QImage &image)
{
    if (image.isNull()) {
        setQrPlaceholder(QStringLiteral("二维码暂不可用，请使用下方链接"));
        return;
    }

    m_qrLabel->setText(QString());
    m_qrLabelRight->setText(QString());
    m_qrLabel->hide();
    m_qrLabelRight->hide();
    m_qrCaption->hide();
    if (image.width() > image.height() * 1.2) {
        // 双码并排图：拆成左右两张、裁掉边距，各占一个码位
        const int w = image.width(), h = image.height();
        const QImage left = cropToCard(image.copy(0, 0, w / 2, h));
        const QImage right = cropToCard(image.copy(w - w / 2, 0, w / 2, h));
        m_qrLabel->setPixmap(fitQr(left));
        m_qrLabelRight->setPixmap(fitQr(right));
    } else {
        // 单码（会话二维码）：居中独占一个码位
        m_qrLabel->setPixmap(fitQr(image));
    }
}

void SupportPromptDialog::setQrPlaceholder(const QString &text)
{
    m_qrLabel->setPixmap(QPixmap());
    m_qrLabel->setText(text);
    m_qrLabelRight->setPixmap(QPixmap());
    m_qrLabelRight->setText(QString());
    m_qrLabelRight->hide();
    m_qrLabel->hide();
    m_qrCaption->hide();
}

void SupportPromptDialog::setBusy(bool busy, const QString &status)
{
    m_busy = busy;
    updateButtons();
    if (!status.isEmpty())
        setStatus(status, false);
}

void SupportPromptDialog::setStatus(const QString &text, bool error)
{
    m_statusLabel->setText(text);
    m_statusLabel->setVisible(!text.isEmpty());
    m_statusLabel->setStyleSheet(error ? QStringLiteral("color: #B23B2E;")
                                       : QStringLiteral("color: #6E5744;"));
}

void SupportPromptDialog::finish(const QString &reason)
{
    closeWithReason(reason);
}

void SupportPromptDialog::reject()
{
    const QString reason = m_closeReason;
    m_closeReason = QStringLiteral("closed");
    QDialog::reject();
    emit dismissed(reason);
}

bool SupportPromptDialog::event(QEvent *event)
{
    // Qt 不会把换行文本 heightForWidth 出的所需高度设为顶层窗口最小高度
    // （minimumSize 按“只显示一行”计算），用户把窗口拖矮时正文第二行会被
    // 垂直截断。这里把“当前宽度下换行所需的最低高度”同步为窗口最小高度：
    // 窗口矮于内容时被顶住，拖窄时高度自动跟着长。
    if (event->type() == QEvent::Resize || event->type() == QEvent::LayoutRequest) {
        if (auto *lay = layout(); lay && lay->hasHeightForWidth()) {
            const int need = lay->totalHeightForWidth(width());
            if (need > 0 && need != minimumHeight())
                setMinimumHeight(need);
        }
    }
    return QDialog::event(event);
}

void SupportPromptDialog::closeWithReason(const QString &reason)
{
    m_closeReason = reason;
    reject();
}

void SupportPromptDialog::updateButtons()
{
    m_supportBtn->setEnabled(!m_busy);
    m_verifyBtn->setEnabled(!m_busy && m_backendAvailable);
    m_neverBtn->setVisible(m_neverVisible);
}

QUrl SupportPromptDialog::mailtoUrl() const
{
    QUrl url(QStringLiteral("mailto:") + m_contactEmail);
    if (!m_contactEmailSubject.isEmpty()) {
        QUrlQuery query;
        query.addQueryItem(QStringLiteral("subject"), m_contactEmailSubject);
        url.setQuery(query);
    }
    return url;
}

} // namespace SupportPrompt
