#!/bin/bash
# 在远程服务器执行

cd ~

# 下载静态编译的 Nginx
wget https://github.com/nginxinc/nginx/archive/refs/tags/release-1.26.0.tar.gz
tar xzf release-1.26.0.tar.gz
cd nginx-release-1.26.0

# 编译（不需要 sudo）
./configure --prefix=$HOME/nginx --without-http_rewrite_module --without-http_gzip_module
make -j4
make install

# 配置
mkdir -p $HOME/nginx/conf/sites

cat > $HOME/nginx/conf/nginx.conf << 'CONF'
worker_processes 1;
events { worker_connections 1024; }
http {
    include mime.types;
    default_type application/octet-stream;

    limit_req_zone $binary_remote_addr zone=api:10m rate=15r/s;

    server {
        listen 8080;

        # 静态文件 - 直接由 Nginx 处理
        location /static/ {
            alias /data/ur02/csh_todo/gem_bgc/web/;
        }

        # API - 反向代理到 Python
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }

        # 页面 - 反向代理到 Python
        location / {
            proxy_pass http://127.0.0.1:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
CONF

# 启动 Nginx
$HOME/nginx/sbin/nginx

echo "Nginx 已启动在端口 8080"
echo "访问 http://IP:8080 即可"
