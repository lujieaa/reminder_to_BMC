# 付款提醒（SupportPrompt）

可复用的“处理成功后评价/赞助弹窗”桌面模块。每次业务处理成功后按可配置频率弹出提示，
引导用户通过 Buy Me a Coffee 赞助或发邮件反馈；用户完成赞助（后端校验通过）后
**永久不再提示**，且第 30 次之后无论是否赞助都停止提示。未赞助不影响软件任何功能。

提供两套完全独立的实现，语义与后端契约一致：

| 实现 | 目录 | 适用 |
|---|---|---|
| C++ / Qt 静态库 | `include/` `src/` `demo/` | Qt Widgets 桌面应用（Qt 5.15+ / Qt 6） |
| Python / PySide6 单文件模块 | `python/` | PySide6 桌面应用（宿主只需 import） |

## 核心行为

- 触发序号：`1, 2, 3, 6, 7, 10, 13, 16, 19, 22, 25, 28, 30, 33, 36, 38, 40`（第 40 次为最后一次）
- 按钮策略：
  - **前 3 次**只显示「稍后再说」（点了即下次触发再提醒）
  - **第 4 次起**才出现「不再提醒」；点击后**不是永久关闭**，而是跳过 N 次成功
    （默认 5 次，`neverRemindSkipCount` 可配）后再恢复提醒
  - 赞助经后端校验通过（`verified=true`）后才**永久**不再提示
- 赞助确认采用**后端校验 + 收款方手动确认**：点“去买咖啡”创建支付会话 → 用户扫码付款 →
  点“我已完成支持”调用 `GET /support/verify?sid=...`；收款方在 `/admin` 后台手动确认
  是否收到款 → 确认后 `verified=true`，应用即永久关闭提示
- 弹窗内容：讨喜咖啡杯图标、标题“可以请我喝杯咖啡吗？”、评价/反馈邮箱、
  支持入口、四个按钮（稍后再说 / 不再提醒 / 去买咖啡 / 我已完成支持）
- 点击「去买咖啡」后打开支付页面；`mock` 模式直接显示
  `resources/个人收款码.png` 中真实可收款的微信/支付宝二维码，
  图片内金额为 **19.90 元人民币**。二维码不再显示在弹窗内。
- 本地持久化（`successCount` / `suppressed` / `suppressUntilCount`）：C++ 版用 `QSettings`，
  Python 版同样用 `QSettings`
- 17 条中文文案（`prompts_zh.json`），每条都用“只买一次就行”的语气

## 后端接口契约

```
POST /support/session/create
  请求: { appId, platform, language, promptKey, successCount, timestamp }
  响应: { "code": 0, "data": { supportSessionId, coffeeCheckoutUrl,
                               qrPngUrl?, expiresAt? } }

GET /support/verify?sid=...
  响应: { "code": 0, "data": { "verified": true|false,
                               "status": "paid|pending|rejected|not_found|expired" } }
```

`code != 0` 表示业务错误，`msg` 为可直接展示的错误信息。

### 收款方手动确认（生产后端需实现）

用户扫码付款到收款方账户后，收款方需要手动确认是否到账，结果再回传给应用：

```
GET  /admin              # 收款方后台：列出所有会话，显示待确认/已收到/未收到
POST /admin/confirm?sid=...   # 收款方确认已收到款 → verify 返回 verified=true
POST /admin/reject?sid=...    # 收款方确认未收到款 → verify 返回 status=rejected
```

应用侧轮询 `GET /support/verify?sid=...`：
- `status=paid`（`verified=true`）→ 永久关闭提示
- `status=rejected` → 提示“收款方暂未确认收到款”
- `status=pending` → 提示“收款方还在确认中”，用户稍后再点“我已完成支持”

`tools/mock_backend.py` 内置了 `/admin` 页面用于联调。

支付后端默认创建 **19.90 元**订单（`COFFEE_AMOUNT_FEN=1990`）。
`mock` 模式通过 `PAYMENT_QR_IMAGE_PATH` 指定真实个人收款码图片；
留空时本地自动读取 `resources/个人收款码.png`，FC 部署包会自动携带该图片。
个人收款码可以实际收款，但不能像商户支付 API 一样自动回调确认到账，
因此仍需在 `/admin` 页面手动确认。

## 快速开始（Python 版）

```bash
pip install -r requirements.txt

# 终端 1：启动联调用 mock 后端（不可用于生产）
python tools/mock_backend.py

# 终端 2：运行演示
python python/demo_support_prompt.py
```

集成到宿主项目：

```python
from support_prompt import SupportPrompt, SupportConfig

cfg = SupportConfig(
    app_id="my-pdf-tool",
    api_base_url="https://api.example.com",     # 留空 = 离线模式（无法自动确认赞助）
    contact_email="you@example.com",
    checkout_url="https://www.buymeacoffee.com/lujieaa",
)
prompt = SupportPrompt(cfg, parent=main_window)
prompt.on_process_success()                     # 每次处理成功后调用
```

## 构建（C++ 版，需要 Qt SDK）

```bash
cmake -S . -B build -DCMAKE_PREFIX_PATH=C:/Qt/6.8.0/mingw_64
cmake --build build
./build/SupportPromptDemo        # 演示宿主（先启动 mock 后端）
ctest --test-dir build           # 纯策略单测（不依赖 Qt）
```

C++ 侧宿主集成：

```cpp
auto *prompt = new SupportPrompt::SupportPrompt(this);
SupportPrompt::Config cfg;
cfg.appId = "my-app";
cfg.apiBaseUrl = QUrl("https://api.example.com");
cfg.contactEmail = "you@example.com";
cfg.fallbackQrImagePath = ":/images/coffee_qr.png";
prompt->init(cfg, mainWindow);
prompt->onProcessSuccess();       // 每次处理成功后调用
```

## 目录结构

```
├── CMakeLists.txt              # C++ 版构建入口
├── include/supportprompt/      # C++ 公开头文件
├── src/                        # C++ 实现（策略/弹窗/网络/持久化）
├── python/
│   ├── support_prompt.py       # Python 模块本体（单文件）
│   ├── prompts_zh.json         # 13 条中文文案
│   └── demo_support_prompt.py  # Python 演示宿主
├── resources/                  # 文案（C++ 用）、.qrc、本地收款码
├── demo/                       # C++ 演示宿主
├── tools/mock_backend.py       # 联调用模拟支付后端
└── tests/test_promptpolicy.cpp # 纯 C++ 策略单测
```

## 注意事项

- `tools/mock_backend.py` 仅供本地联调，支付状态存内存，重启即清空；生产环境需
  自行实现后端，把 `supportSessionId` 与真实支付订单关联（如通过 URL 参数/备注）。
- 模块任何网络/配置异常都不会阻塞或影响宿主核心功能。
- 二维码图片请求限制 4MB；网络请求默认 8 秒超时，可配置。
