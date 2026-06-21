#!/usr/bin/env bash
set -euo pipefail

# ── 1. 本地：导出最新数据 ──
pg_dump -h /tmp -U charlie -Fc -d gem_portal -n gem --no-owner -f bgcmap.dump

# ── 2. 传到远程服务器 ──
REMOTE="user@192.168.24.7"
scp bgcmap.dump "$REMOTE":/tmp/bgcmap.dump

# ── 3. 远程部署 ──
ssh "$REMOTE" << 'EOF'
set -euo pipefail

# 删旧库，建新库
sudo -u postgres psql -c "DROP DATABASE IF EXISTS bgcmap;"
sudo -u postgres psql -c "CREATE DATABASE bgcmap;"

# 创建 trgm 扩展
sudo -u postgres psql -d bgcmap -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 导入数据
sudo -u postgres pg_restore -d bgcmap -Fc -n gem --no-owner /tmp/bgcmap.dump

# 安装依赖（如果还没有）
pip3 install -r /opt/spire/requirements.txt

# 启动服务
cd /opt/spire
PGHOST=/tmp PGDATABASE=bgcmap PGUSER=charlie \
  nohup python3 server_pg.py --host 0.0.0.0 --port 8000 > /tmp/pg_srv.log 2>&1 &

echo "部署完成，访问 http://192.168.24.7:8000"
EOF
