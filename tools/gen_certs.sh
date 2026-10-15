#!/usr/bin/env bash
# 重新生成 dePixPin 自签证书（CA + openapi.youdao.com 叶子证书）
# 需要 openssl（Git Bash 自带）。已安装旧证书的设备无需重跑；
# 重跑后需在新设备上重新执行 install.bat 安装新的根证书。
set -e
cd "$(dirname "$0")/../server/certs"

openssl req -x509 -newkey rsa:2048 -keyout depixpin-ca.key -out depixpin-ca.crt \
  -days 3650 -nodes -subj "//CN=dePixPin Root CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

cat > san.cnf <<'EOF'
[req]
distinguished_name = dn
req_extensions = ext
[dn]
[ext]
subjectAltName = DNS:openapi.youdao.com
EOF

openssl req -newkey rsa:2048 -keyout youdao.key -out youdao.csr -nodes \
  -subj "//CN=openapi.youdao.com" -config san.cnf
openssl x509 -req -in youdao.csr -CA depixpin-ca.crt -CAkey depixpin-ca.key \
  -CAcreateserial -out youdao.crt -days 825 -extensions ext -extfile san.cnf

rm -f youdao.csr san.cnf
echo "证书已生成：depixpin-ca.crt / youdao.crt（+ 对应 .key，私钥勿提交 git）"
