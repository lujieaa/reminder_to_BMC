# -*- coding: utf-8 -*-
"""HTTP 服务（控制层）：路由 + 页面。

对外接口：
    - make_server(cfg) -> ThreadingHTTPServer
    - main()：入口

路由：
    POST /support/session/create   创建支持会话（并向支付渠道下单）
    GET  /support/verify?sid=...   客户端轮询支付状态
    GET  /payment-qr.png           mock 模式的真实个人收款码图片
    GET  /qr/<sid>.png             真实支付渠道的会话二维码
    GET  /pay/<sid>                支付引导/状态页
    POST /notify/wechat            微信支付回调（自动确认）
    POST /notify/alipay            支付宝回调（自动确认）
    GET  /admin                    收款方后台（mock 手动确认 / 真渠道对账）
    POST /admin/confirm|reject     人工确认/驳回（兜底通道）
    GET  /health                   存活检查

依赖模块：config / store / payments
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ""):
    # 支持 `python tools/backend/server.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "backend"

from .config import BackendConfig
from .payments import PaymentProvider, make_provider
from .store import SessionStore, iso, now_utc

try:
    import qrcode
except ImportError:  # pragma: no cover
    qrcode = None


def make_qr_png(text: str) -> bytes | None:
    if qrcode is None:
        return None
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #FFF8F0; color: #3E2B1F;
         font-family: "Microsoft YaHei UI", "PingFang SC", sans-serif; }}
  main {{ max-width: 560px; margin: 8vh auto; padding: 32px;
          background: #FFFFFF; border: 1px solid #E8D9CB; border-radius: 12px;
          box-shadow: 0 8px 30px rgba(107, 81, 64, .08); }}
  h1 {{ font-size: 22px; margin: 0 0 12px; }}
  p {{ line-height: 1.7; color: #6B5140; }}
  button {{ margin-top: 12px; padding: 10px 18px; border: none; border-radius: 6px;
            background: #C87941; color: #fff; font-size: 15px; cursor: pointer; }}
  button:hover {{ background: #B76C36; }}
  code {{ background: #F5EDE5; padding: 2px 6px; border-radius: 4px; }}
</style>
</head>
<body><main>{body}</main></body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "SupportPromptBackend/1.0"

    # 由 make_server 注入
    cfg: BackendConfig
    store: SessionStore
    provider: PaymentProvider
    public_base: str

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(f"[backend] {self.address_string()} {fmt % args}")

    # -- 基础输出 ------------------------------------------------------------

    def send_bytes(self, status: int, body: bytes,
                   content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_bytes(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def send_error_json(self, status: int, code: int, message: str) -> None:
        self.send_json(status, {"code": code, "msg": message})

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        return self.rfile.read(max(0, length)) if length > 0 else b""

    def read_json(self) -> dict | None:
        raw = self.read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    # -- GET ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.send_json(200, {"code": 0, "data": {
                "ok": True, "provider": self.provider.name}})
            return

        if path == "/support/verify":
            self._handle_verify(parsed.query)
            return

        if path == "/payment-qr.png":
            self._handle_payment_qr()
            return

        if path.startswith("/qr/") and path.endswith(".png"):
            self._handle_qr(path[len("/qr/"):-len(".png")], parsed.query)
            return

        if path.startswith("/pay/"):
            self._handle_pay(path[len("/pay/"):])
            return

        if path == "/admin":
            self._handle_admin()
            return

        if path == "/":
            body = (
                f"<h1>SupportPrompt 后端</h1>"
                f"<p>支付渠道：<code>{self.provider.name}</code></p>"
                f"<p>接口：<code>POST /support/session/create</code>、"
                f"<code>GET /support/verify?sid=...</code></p>"
                f"<p>收款方后台：<a href=\"/admin\">/admin</a></p>"
            )
            self.send_bytes(200, page("后端", body).encode("utf-8"),
                            "text/html; charset=utf-8")
            return

        self.send_error_json(404, 1002, "not_found")

    def _handle_verify(self, query: str) -> None:
        sid = parse_qs(query).get("sid", [""])[0]
        if not sid:
            self.send_error_json(400, 1001, "缺少 sid")
            return
        session = self.store.get(sid)
        if session is None:
            self.send_json(200, {"code": 0, "data": {
                "verified": False, "status": "not_found"}})
            return
        if self.store.is_expired(session):
            status, verified = "expired", False
        elif session.get("confirmed") == "paid":
            status, verified = "paid", True
        elif session.get("confirmed") == "rejected":
            status, verified = "rejected", False
        else:
            status, verified = "pending", False
        self.send_json(200, {"code": 0, "data": {
            "verified": verified, "status": status}})

    def _payment_qr_path(self) -> Path:
        if self.cfg.payment_qr_image_path:
            return Path(self.cfg.payment_qr_image_path).expanduser()

        # FC 部署包将图片放在 backend 包旁边；本地联调从仓库 resources 目录读取。
        packaged = Path(__file__).resolve().parent.parent / "payment_qr.png"
        local = Path(__file__).resolve().parents[2] / "resources" / "个人收款码.png"
        return packaged if packaged.is_file() else local

    def _handle_payment_qr(self) -> None:
        path = self._payment_qr_path()
        try:
            image = path.read_bytes()
        except OSError as exc:
            self.send_error_json(
                503, 5001, f"个人收款码图片不可用：{path}（{exc}）")
            return
        if not image:
            self.send_error_json(503, 5001, "个人收款码图片为空")
            return
        self.send_bytes(200, image, "image/png")

    def _handle_qr(self, sid: str, query: str = "") -> None:
        session = self.store.get(sid)
        if session is None:
            self.send_error_json(404, 1002, "session_not_found")
            return
        if self.provider.name == "mock":
            self._handle_payment_qr()
            return

        # 真实渠道编码支付串（微信 code_url / 支付宝 qr_code）。
        text = session.get("qrText")
        if not text:
            self.send_error_json(503, 5002, "当前支付会话尚未生成真实支付二维码")
            return
        png = make_qr_png(text)
        if png is None:
            self.send_error_json(503, 5000,
                                 "缺少 qrcode 依赖：pip install \"qrcode[pil]\"")
            return
        self.send_bytes(200, png, "image/png")

    def _handle_pay(self, sid: str) -> None:
        session = self.store.get(sid)
        if session is None:
            self.send_bytes(404, page("会话不存在",
                "<h1>会话不存在</h1><p>请回到软件重新点击“去买咖啡”。</p>"
                ).encode("utf-8"), "text/html; charset=utf-8")
            return

        amount = f"¥{self.cfg.coffee_amount_fen / 100:.2f}"
        confirmed = session.get("confirmed")
        if confirmed == "paid":
            body = ("<h1>已收到你的支持 ♡</h1>"
                    "<p>请回到软件查看致谢提示，以后就不会再弹提醒啦。</p>")
        elif confirmed == "rejected":
            body = ("<h1>收款方未确认收到款</h1>"
                    "<p>请检查是否已成功支付；如有疑问可通过软件内的邮箱联系。</p>")
        else:
            tip = ("支付完成后系统自动确认，回到软件稍等几秒即可。"
                   if self.provider.name != "mock" else
                   "付款完成后请回到软件点击「我已完成支持」，收款方确认到账后即可解锁。")
            if self.provider.name == "mock":
                payment_markup = (
                    "<p>请扫描下方图片中对应的微信或支付宝收款码，"
                    "图片内已标注支付金额 <b>¥19.90</b>。</p>"
                    '<p><img src="/payment-qr.png" width="720" '
                    'style="max-width:100%;height:auto;" alt="微信和支付宝个人收款码"></p>'
                )
            else:
                channel_name = "微信支付" if self.provider.name == "wechat" else "支付宝"
                payment_markup = (
                    f"<p>请使用{channel_name}扫码付款，金额 <b>{amount}</b>。</p>"
                    f'<p><img src="/qr/{sid}.png" width="240" height="240" '
                    f'alt="{channel_name}二维码"></p>'
                )
            body = (
                f"<h1>请我喝杯咖啡</h1>"
                f"{payment_markup}"
                f"<p>会话编号：<code>{sid}</code></p>"
                f'<p style="font-size:13px;color:#8A6F57;">{tip}</p>'
            )
        self.send_bytes(200, page("请我喝杯咖啡", body).encode("utf-8"),
                        "text/html; charset=utf-8")

    def _handle_admin(self) -> None:
        rows = []
        for sid, s in self.store.all_sorted():
            confirmed = s.get("confirmed")
            if confirmed == "paid":
                badge = '<span style="color:#2E7D32;font-weight:600;">已支付</span>'
                actions = s.get("channelOrderNo", "") or s.get("confirmedAt", "")
            elif confirmed == "rejected":
                badge = '<span style="color:#C62828;font-weight:600;">未收到</span>'
                actions = (f'<form method="post" action="/admin/confirm?sid={sid}" '
                           f'style="display:inline;">'
                           f'<button type="submit" style="background:#2E7D32;">'
                           f'更正为已收到</button></form>')
            else:
                badge = '<span style="color:#E65100;font-weight:600;">待确认</span>'
                actions = (
                    f'<form method="post" action="/admin/confirm?sid={sid}" '
                    f'style="display:inline;">'
                    f'<button type="submit" style="background:#2E7D32;">'
                    f'确认已收到款</button></form> '
                    f'<form method="post" action="/admin/reject?sid={sid}" '
                    f'style="display:inline;">'
                    f'<button type="submit" style="background:#C62828;">'
                    f'未收到款</button></form>'
                )
            rows.append(
                f"<tr>"
                f"<td><code>{sid[:12]}…</code></td>"
                f"<td>{s.get('appId','')}</td>"
                f"<td>第 {s.get('successCount', 0)} 次</td>"
                f"<td>{s.get('createdAt','')}</td>"
                f"<td>{badge}</td>"
                f"<td>{actions}</td>"
                f"</tr>"
            )
        table = (
            "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
            "<thead><tr style='background:#F5EDE5;'>"
            "<th style='padding:8px;text-align:left;'>会话</th>"
            "<th style='padding:8px;text-align:left;'>应用</th>"
            "<th style='padding:8px;text-align:left;'>次数</th>"
            "<th style='padding:8px;text-align:left;'>创建时间</th>"
            "<th style='padding:8px;text-align:left;'>状态</th>"
            "<th style='padding:8px;text-align:left;'>操作/平台单号</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
        tip = ("真实支付渠道已启用：平台回调自动确认，本页用于对账与人工兜底。"
               if self.provider.name != "mock" else
               "用户扫码付款到你的账户后，在这里手动确认是否收到款。")
        body = f"<h1>收款方后台</h1><p>{tip}</p>" + table
        self.send_bytes(200, page("收款方后台", body).encode("utf-8"),
                        "text/html; charset=utf-8")

    # -- POST -----------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/support/session/create":
            self._handle_create_session()
            return

        if path in ("/notify/wechat", "/notify/alipay"):
            self._handle_notify(path)
            return

        if path == "/admin/confirm":
            sid = parse_qs(parsed.query).get("sid", [""])[0]
            if not self.store.mark(sid, "paid"):
                self.send_error_json(404, 1002, "session_not_found")
                return
            self.redirect("/admin")
            return

        if path == "/admin/reject":
            sid = parse_qs(parsed.query).get("sid", [""])[0]
            if not self.store.mark(sid, "rejected"):
                self.send_error_json(404, 1002, "session_not_found")
                return
            self.redirect("/admin")
            return

        self.send_error_json(404, 1002, "not_found")

    def _handle_create_session(self) -> None:
        body = self.read_json()
        if body is None:
            self.send_error_json(400, 1001, "invalid_json")
            return
        app_id = str(body.get("appId") or "").strip()
        if not app_id:
            self.send_error_json(400, 1001, "appId_required")
            return

        session = self.store.create(
            app_id=app_id,
            prompt_key=str(body.get("promptKey") or ""),
            success_count=int(body.get("successCount") or 0))
        sid = session["sid"]

        # 向支付渠道下单：真实渠道拿支付串生成二维码；mock 回落 /pay 页
        order = self.provider.create_order(
            sid, self.cfg.coffee_amount_fen, "请我喝杯咖啡")
        if order and order.get("qr_text"):
            self.store.set_qr_text(sid, order["qr_text"])

        self.send_json(200, {"code": 0, "data": {
            "supportSessionId": sid,
            "coffeeCheckoutUrl": f"{self.public_base}/pay/{sid}",
            "qrPngUrl": f"{self.public_base}/qr/{sid}.png",
            "expiresAt": session["expiresAt"],
        }})

    def _handle_notify(self, path: str) -> None:
        """平台回调：验签/解密 → 取 out_trade_no(=sid) → 标记已支付。"""
        if path != self.provider.notify_path:
            self.send_bytes(400, b"fail")
            return
        headers = {k: v for k, v in self.headers.items()}
        raw = self.read_body()
        sid, order_no = self.provider.verify_callback(headers, raw)
        if sid and self.store.mark(sid, "paid", channel_order_no=order_no or ""):
            print(f"[backend] 支付回调确认: sid={sid} order={order_no}")
            self.send_bytes(200, self.provider.callback_ok_body())
            return
        print(f"[backend] 支付回调被拒绝: {order_no or sid}")
        self.send_bytes(400, b"fail")


def make_server(cfg: BackendConfig) -> ThreadingHTTPServer:
    provider = make_provider(cfg)
    store = SessionStore(cfg.session_ttl_seconds)

    class BoundHandler(Handler):
        pass

    BoundHandler.cfg = cfg
    BoundHandler.store = store
    BoundHandler.provider = provider
    BoundHandler.public_base = cfg.notify_base_url or f"http://{cfg.host}:{cfg.port}"
    return ThreadingHTTPServer((cfg.host, cfg.port), BoundHandler)


def main() -> None:
    if qrcode is None:
        print('[backend] 警告：未安装 qrcode，二维码不可用。pip install "qrcode[pil]"')
    cfg = BackendConfig.from_env()
    server = make_server(cfg)
    print(f"[backend] listening on http://{cfg.host}:{cfg.port} "
          f"provider={cfg.provider}")
    if cfg.provider != "mock":
        print(f"[backend] 回调地址: {cfg.notify_base_url}"
              f"{server.RequestHandlerClass.provider.notify_path}")
    print(f"[backend] 收款方后台: http://{cfg.host}:{cfg.port}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[backend] 已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
