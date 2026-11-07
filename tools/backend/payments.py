# -*- coding: utf-8 -*-
"""支付渠道（逻辑层，可插拔）。

对外接口：
    - PaymentProvider：抽象基类
        create_order(sid, amount_fen, description) -> dict | None
            成功返回 {"qr_text": 二维码编码内容}；失败返回 None
        verify_callback(headers, raw_body) -> tuple[str | None, str]
            校验平台回调签名/解密，成功返回 (out_trade_no 即 sid, 平台订单号)，
            失败返回 (None, 错误原因)
        callback_ok_body() -> bytes
            给平台的成功回执（各平台格式不同）
    - make_provider(cfg) -> PaymentProvider

依赖模块：config.BackendConfig；cryptography（微信/支付宝验签）
被依赖：server
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from .config import BackendConfig

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover
    hashes = serialization = padding = AESGCM = None


def _http_post_json(url: str, payload: dict, headers: dict | None = None,
                    timeout: int = 10) -> tuple[int, dict]:
    """标准库 POST JSON；返回 (http_status, 解析后的 json 或 {})。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}
    except OSError:
        return 0, {}


def _load_private_key(path_or_pem: str):
    data = (Path(path).read_bytes()
            if (path := Path(path_or_pem)).exists() else path_or_pem.encode("utf-8"))
    return serialization.load_pem_private_key(data, password=None)


class PaymentProvider:
    name = "base"
    notify_path = "/notify/base"

    def create_order(self, sid: str, amount_fen: int, description: str) -> dict | None:
        raise NotImplementedError

    def verify_callback(self, headers: dict, raw_body: bytes) -> tuple[str | None, str]:
        raise NotImplementedError

    def callback_ok_body(self) -> bytes:
        return b"success"


class MockProvider(PaymentProvider):
    """个人收款码模式：不下真实订单，二维码指向本站 /pay 页，收款方人工确认。"""

    name = "mock"
    notify_path = ""

    def create_order(self, sid: str, amount_fen: int, description: str) -> dict | None:
        return {"qr_text": ""}  # 空 = server 回落为 /pay/<sid> 链接

    def verify_callback(self, headers: dict, raw_body: bytes) -> tuple[str | None, str]:
        return None, "mock 渠道无回调，请在 /admin 手动确认"


class WechatPayProvider(PaymentProvider):
    """微信支付 Native（APIv3）。下单得 code_url；回调验签 + AES-GCM 解密取 out_trade_no。"""

    name = "wechat"
    notify_path = "/notify/wechat"
    _ORDER_URL = "https://api.mch.weixin.qq.com/v3/pay/transactions/native"

    def __init__(self, cfg: BackendConfig):
        if hashes is None:
            raise RuntimeError("缺少 cryptography 依赖：pip install cryptography")
        self._cfg = cfg
        self._mch_key = _load_private_key(cfg.wechat_private_key_path)
        self._platform_key = serialization.load_pem_public_key(
            cfg.wechat_platform_public_key.encode("utf-8"))

    # -- 下单 ----------------------------------------------------------------

    def _authorization(self, method: str, url_path: str, body: str) -> str:
        import secrets as _secrets
        timestamp = str(int(datetime.now().timestamp()))
        nonce = _secrets.token_hex(16)
        message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
        signature = base64.b64encode(self._mch_key.sign(
            message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())).decode()
        return (
            f'WECHATPAY-SHA256-RSA2048 mchid="{self._cfg.wechat_mchid}",'
            f'nonce_str="{nonce}",signature="{signature}",'
            f'timestamp="{timestamp}",serial_no="{self._cfg.wechat_serial_no}"')

    def create_order(self, sid: str, amount_fen: int, description: str) -> dict | None:
        cfg = self._cfg
        payload = {
            "mchid": cfg.wechat_mchid,
            "appid": cfg.wechat_appid,
            "description": description[:127],
            "out_trade_no": sid,                 # ★ sid 即商户订单号，回调原样带回
            "notify_url": cfg.notify_base_url + self.notify_path,
            "amount": {"total": amount_fen, "currency": "CNY"},
        }
        body = json.dumps(payload, ensure_ascii=False)
        status, resp = _http_post_json(
            self._ORDER_URL, payload,
            headers={"Authorization": self._authorization(
                "POST", "/v3/pay/transactions/native", body),
                "Accept": "application/json"})
        if status == 200 and resp.get("code_url"):
            return {"qr_text": resp["code_url"]}
        print(f"[backend] 微信下单失败: http={status} resp={resp}")
        return None

    # -- 回调验签 + 解密 ------------------------------------------------------

    def verify_callback(self, headers: dict, raw_body: bytes) -> tuple[str | None, str]:
        try:
            timestamp = headers.get("Wechatpay-Timestamp", "")
            nonce = headers.get("Wechatpay-Nonce", "")
            signature = headers.get("Wechatpay-Signature", "")
            message = f"{timestamp}\n{nonce}\n{raw_body.decode('utf-8')}\n"
            self._platform_key.verify(
                base64.b64decode(signature), message.encode("utf-8"),
                padding.PKCS1v15(), hashes.SHA256())

            root = json.loads(raw_body.decode("utf-8"))
            resource = root["resource"]
            plain = AESGCM(self._cfg.wechat_apiv3_key.encode("utf-8")).decrypt(
                resource["nonce"].encode("utf-8"),
                base64.b64decode(resource["ciphertext"]),
                resource.get("associated_data", "").encode("utf-8") or None)
            trade = json.loads(plain.decode("utf-8"))
        except Exception as exc:
            return None, f"回调验签/解密失败: {exc}"

        if trade.get("trade_state") != "SUCCESS":
            return None, f"trade_state={trade.get('trade_state')}"
        return trade.get("out_trade_no"), trade.get("transaction_id", "")

    def callback_ok_body(self) -> bytes:
        return b'{"code":"SUCCESS","message":"\xe6\x88\x90\xe5\x8a\x9f"}'


class AlipayProvider(PaymentProvider):
    """支付宝当面付（alipay.trade.precreate）。下单得 qr_code；回调 RSA2 验签。"""

    name = "alipay"
    notify_path = "/notify/alipay"
    _GATEWAY = "https://openapi.alipay.com/gateway.do"

    def __init__(self, cfg: BackendConfig):
        if hashes is None:
            raise RuntimeError("缺少 cryptography 依赖：pip install cryptography")
        self._cfg = cfg
        self._app_key = _load_private_key(cfg.alipay_private_key_path)
        self._alipay_key = serialization.load_pem_public_key(
            cfg.alipay_public_key.encode("utf-8"))

    @staticmethod
    def _sign_content(params: dict) -> str:
        """按 key 字典序拼接 k=v&...（不含 sign / sign_type）。"""
        return "&".join(f"{k}={params[k]}" for k in sorted(params)
                        if k not in ("sign", "sign_type") and params[k] not in (None, ""))

    def create_order(self, sid: str, amount_fen: int, description: str) -> dict | None:
        cfg = self._cfg
        biz = json.dumps({
            "out_trade_no": sid,                 # ★ sid 即商户订单号，回调原样带回
            "total_amount": f"{amount_fen / 100:.2f}",
            "subject": description[:256],
        }, ensure_ascii=False)
        params = {
            "app_id": cfg.alipay_appid,
            "method": "alipay.trade.precreate",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": cfg.notify_base_url + self.notify_path,
            "biz_content": biz,
        }
        sign = base64.b64encode(self._app_key.sign(
            self._sign_content(params).encode("utf-8"),
            padding.PKCS1v15(), hashes.SHA256())).decode()
        params["sign"] = sign

        body = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(self._GATEWAY, data=body, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                root = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            print(f"[backend] 支付宝下单网络错误: {exc}")
            return None

        resp = root.get("alipay_trade_precreate_response", {})
        if resp.get("code") == "10000" and resp.get("qr_code"):
            return {"qr_text": resp["qr_code"]}
        print(f"[backend] 支付宝下单失败: {resp.get('msg')} {resp.get('sub_msg')}")
        return None

    def verify_callback(self, headers: dict, raw_body: bytes) -> tuple[str | None, str]:
        try:
            form = {k: v[0] for k, v in
                    urllib.parse.parse_qs(raw_body.decode("utf-8")).items()}
            signature = form.get("sign", "")
            content = self._sign_content(form)
            self._alipay_key.verify(
                base64.b64decode(signature), content.encode("utf-8"),
                padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            return None, f"回调验签失败: {exc}"

        if form.get("trade_status") != "TRADE_SUCCESS":
            return None, f"trade_status={form.get('trade_status')}"
        return form.get("out_trade_no"), form.get("trade_no", "")

    def callback_ok_body(self) -> bytes:
        return b"success"


def make_provider(cfg: BackendConfig) -> PaymentProvider:
    """按配置实例化渠道；真实渠道缺少配置时直接报错（避免上线后静默降级）。"""
    if cfg.provider in ("", "mock"):
        return MockProvider()
    missing = cfg.missing_for(cfg.provider)
    if missing:
        raise RuntimeError(
            f"PAY_PROVIDER={cfg.provider} 缺少配置: {', '.join(missing)}"
            "（通过环境变量设置；或改用 PAY_PROVIDER=mock）")
    if cfg.provider == "wechat":
        return WechatPayProvider(cfg)
    if cfg.provider == "alipay":
        return AlipayProvider(cfg)
    raise RuntimeError(f"未知 PAY_PROVIDER: {cfg.provider}（可选 mock / wechat / alipay）")
