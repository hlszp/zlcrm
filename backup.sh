#!/bin/bash
# 每日备份 SQLite 数据库与附件，保留最近 30 天
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
BK="$BASE/backups/$(date +%Y%m%d_%H%M%S)"
DB="${CRM_DB:-$BASE/data/crm.db}"
UPLOADS="${CRM_UPLOAD_DIR:-$(dirname "$DB")/uploads}"
mkdir -p "$BK"
python3 - "$DB" "$BK/crm.db" <<'EOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
s.backup(d)
d.close(); s.close()
EOF
[ -d "$UPLOADS" ] && cp -r "$UPLOADS" "$BK/uploads" 2>/dev/null || true
find "$BASE/backups" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
echo "backup ok: $BK"
