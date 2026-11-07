# -*- coding: utf-8 -*-
"""后端配置（数据层）。

对外接口：
    - BackendConfig：全部配置字段 + from_env() + missing_for()

依赖模块：仅标准库
被依赖：payments / server
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 各支付渠道必需的配置项（缺失时拒绝启动，避免上线后静默降级）
_PROVIDER_REQUIRED = {
    "wechat": (
        "notify_base_url", "wechat_mchid", "wechat_appid", "wechat_serial_no",
        "wechat_private_key_path", "wechat_apiv3_key", "wechat_platform_public_key",
    ),
    "alipay": (
        "notify_base_url", "alipay_appid", "alipay_private_key_path",
        "alipay_public_key",
    ),
}


@dataclass
class BackendConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    provider: str = "mock"                # mock / wechat / alipay
    notify_base_url: str = ""             # 公网 HTTPS 地址，如 https://pay.example.com
    coffee_amount_fen: int = 1990         # 咖啡价格（分）
    session_ttl_seconds: int = 30 * 60
    # mock 模式使用的真实个人收款码图片；留空时由服务自动探测。
    payment_qr_image_path: str = ""

    # 微信支付（Native 扫码，APIv3）
    wechat_mchid: str = ""
    wechat_appid: str = ""
    wechat_serial_no: str = ""            # 商户证书序列号
    wechat_private_key_path: str = ""     # apiclient_key.pem 路径
    wechat_apiv3_key: str = ""            # APIv3 密钥（回调报文解密）
    wechat_platform_public_key: str = ""  # 微信平台公钥 PEM 内容（回调验签）

    # 支付宝（当面付预下单）
    alipay_appid: str = ""
    alipay_private_key_path: str = ""     # 应用私钥 PEM 路径
    alipay_public_key: str = ""           # 支付宝公钥 PEM 内容

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        env = os.environ.get
        # 云函数 Custom Runtime 会注入 PORT（阿里云 FC）或 FC_LISTEN_PORT
        # 启动脚本里也可以直接设 HOST=0.0.0.0 PORT=xxx
        port = env("PORT", "")
        if not port:
            port = env("FC_LISTEN_PORT", "")
        port = port or "8787"

        host = env("HOST", "")
        if not host:
            host = "0.0.0.0" if (env("FC_LISTEN_PORT", "") or env("FUNC_ID", "")) else "127.0.0.1"

        return cls(
            host=host,
            port=int(port),
            provider=env("PAY_PROVIDER", "mock").strip().lower(),
            notify_base_url=env("NOTIFY_BASE_URL", "").rstrip("/"),
            coffee_amount_fen=int(env("COFFEE_AMOUNT_FEN", "1990")),
            session_ttl_seconds=int(env("SESSION_TTL_SECONDS", str(30 * 60))),
            payment_qr_image_path=env("PAYMENT_QR_IMAGE_PATH", ""),
            wechat_mchid=env("WECHAT_MCHID", ""),
            wechat_appid=env("WECHAT_APPID", ""),
            wechat_serial_no=env("WECHAT_SERIAL_NO", ""),
            wechat_private_key_path=env("WECHAT_PRIVATE_KEY_PATH", ""),
            wechat_apiv3_key=env("WECHAT_APIV3_KEY", ""),
            wechat_platform_public_key=env("WECHAT_PLATFORM_PUBLIC_KEY", ""),
            alipay_appid=env("ALIPAY_APPID", ""),
            alipay_private_key_path=env("ALIPAY_PRIVATE_KEY_PATH", ""),
            alipay_public_key=env("ALIPAY_PUBLIC_KEY", ""),
        )

    def missing_for(self, provider: str) -> list[str]:
        """返回该渠道缺失的配置项名；空列表表示齐备。"""
        required = _PROVIDER_REQUIRED.get(provider, ())
        return [name for name in required if not getattr(self, name)]
