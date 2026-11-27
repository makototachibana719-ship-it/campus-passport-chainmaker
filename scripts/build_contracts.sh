#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir/contract"
command -v go >/dev/null
command -v 7z >/dev/null
names=(jifen_zuodequandui_campus badge_zuodequandui_campus task_zuodequandui_campus)
for name in "${names[@]}"; do
  if [[ -e "build/$name" || -e "build/$name.7z" ]]; then
    printf '停止：已有同名产物 build/%s，请先自行保存和处理。\n' "$name" >&2
    exit 1
  fi
done
mkdir -p build
go mod download
go mod verify
for name in "${names[@]}"; do
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o "build/$name" .
  (cd build && 7z a -t7z "$name.7z" "$name" && 7z t "$name.7z")
done
sha256sum build/*.7z
printf '仅完成本地编译打包；没有部署、授权或链上写入。\n'
