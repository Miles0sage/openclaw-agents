#!/bin/bash
# OpenClaw Log Rotation Script
# Runs daily at midnight via cron.
# Rotates logs in ./logs/ and /tmp/openclaw/.
# Keeps last 7 days of logs, compresses old ones.

set -uo pipefail

LOG_DIRS=(
    "./logs"
    "/tmp/openclaw"
)

KEEP_DAYS=7
TIMESTAMP=$(date '+%Y%m%d')

ts() {
    date '+%Y-%m-%d %H:%M:%S'
}

rotate_dir() {
    local dir="$1"

    if [ ! -d "$dir" ]; then
        echo "$(ts) [ROTATE] Directory does not exist: ${dir} -- skipping"
        return
    fi

    echo "$(ts) [ROTATE] Processing: ${dir}"

    # Rotate current .log files: copy and truncate
    for logfile in "${dir}"/*.log; do
        [ -f "$logfile" ] || continue

        local basename
        basename=$(basename "$logfile")
        local rotated="${dir}/${basename}.${TIMESTAMP}"

        # Only rotate if file has content
        if [ -s "$logfile" ]; then
            cp "$logfile" "$rotated"
            truncate -s 0 "$logfile"
            gzip -f "$rotated" 2>/dev/null || true
            echo "$(ts) [ROTATE] Rotated: ${basename} -> ${basename}.${TIMESTAMP}.gz"
        fi
    done

    # Delete compressed logs older than KEEP_DAYS
    find "$dir" -name "*.log.*.gz" -mtime +"$KEEP_DAYS" -delete 2>/dev/null
    find "$dir" -name "*.log.[0-9]*" -mtime +"$KEEP_DAYS" -delete 2>/dev/null

    # Clean up any stale .tmp files older than 1 day
    find "$dir" -name "*.tmp" -mtime +1 -delete 2>/dev/null

    echo "$(ts) [ROTATE] Done: ${dir} (kept last ${KEEP_DAYS} days)"
}

echo "$(ts) [ROTATE] === Log rotation started ==="

for dir in "${LOG_DIRS[@]}"; do
    rotate_dir "$dir"
done

echo "$(ts) [ROTATE] === Log rotation complete ==="
