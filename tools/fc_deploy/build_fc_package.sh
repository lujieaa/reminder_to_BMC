#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 打包后端代码 + FC 部署入口，生成可上传阿里云 FC Custom Runtime 的 zip 包
#
# 用法（仓库根目录）：
#   chmod +x tools/fc_deploy/bootstrap tools/fc_deploy/build_fc_package.sh
#   bash tools/fc_deploy/build_fc_package.sh
#   → 生成 dist/support-backend-fc.zip，直接上传 FC 控制台即可

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/dist"
STAGE_DIR="$OUT_DIR/_fc_stage"
ZIP_NAME="support-backend-fc.zip"

echo "=== 构建 FC 部署包 ==="
echo "仓库根目录: $REPO_ROOT"

# 清理旧 stage
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

# 1. 放 backend 包（原样）
cp -r "$REPO_ROOT/tools/backend" "$STAGE_DIR/"

# 2. 放 fc_deploy 里的文件（bootstrap / requirements.txt）
cp "$REPO_ROOT/tools/fc_deploy/bootstrap" "$STAGE_DIR/bootstrap"
cp "$REPO_ROOT/tools/fc_deploy/requirements.txt" "$STAGE_DIR/requirements.txt"

# 3. 放置真实个人收款码；mock 模式直接展示此图片，不重新生成二维码
cp "$REPO_ROOT/resources/个人收款码.png" "$STAGE_DIR/payment_qr.png"

# 4. 确保 bootstrap 可执行
chmod +x "$STAGE_DIR/bootstrap"

# 5. 打包
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$ZIP_NAME"
cd "$STAGE_DIR"
zip -r -q "$OUT_DIR/$ZIP_NAME" .
cd "$REPO_ROOT"
rm -rf "$STAGE_DIR"

# 6. 结果
SIZE_KB=$(du -k "$OUT_DIR/$ZIP_NAME" | cut -f1)
echo ""
echo "=== 构建完成 ==="
echo "产物: $OUT_DIR/$ZIP_NAME"
echo "大小: ${SIZE_KB} KB"
echo ""
echo "FC 控制台操作："
echo "  函数计算 → 函数详情 → 代码上传 → 上传 ZIP"
echo "  运行环境：自定义运行时（Custom Runtime）"
echo "  启动命令：bootstrap"
echo "  监听端口：9000（FC 会通过 PORT 环境变量告诉进程）"
echo ""
echo "环境变量（按需设置）："
echo "  PAY_PROVIDER=mock          mock / wechat / alipay"
echo "  SNAPSHOT_PATH=/tmp/sessions.json"
echo "  NOTIFY_BASE_URL=https://你的域名"
echo "  （wechat/alipay 需要更多商户配置）"
