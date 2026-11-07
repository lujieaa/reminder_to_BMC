# -*- coding: utf-8 -*-
"""支持弹窗后端包：会话管理 + 支付平台回调自动确认到账。

模块分层（单向依赖，无循环引用）：
    config    BackendConfig：从环境变量读取商户凭据与监听地址（数据层）
    store     SessionStore：线程安全的会话内存表（数据层）
    payments  PaymentProvider 抽象 + mock / wechat / alipay 三个实现（逻辑层）
    server    HTTP 路由与页面：会话、verify、二维码、回调、admin（控制层）

支付渠道通过 PAY_PROVIDER 环境变量切换：
    mock    个人收款码模式：二维码指向本站 /pay 页，收款方在 /admin 手动确认
    wechat  微信支付 Native：下单返回 code_url 生成二维码，
            支付成功后微信回调 /notify/wechat 自动确认（out_trade_no = sid）
    alipay  支付宝当面付：precreate 返回 qr_code 生成二维码，
            支付成功后支付宝回调 /notify/alipay 自动确认（out_trade_no = sid）

启动：
    python -m tools.backend.server            # 仓库根目录下
    python tools/backend/server.py            # 或任意目录
"""
