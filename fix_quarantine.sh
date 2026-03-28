#!/bin/bash
cd "$(dirname "$0")"
xattr -d com.apple.quarantine *.command 2>/dev/null || true
xattr -d com.apple.quarantine *.sh 2>/dev/null || true
echo "✅ 完了 — .command ファイルが開けるようになりました"
