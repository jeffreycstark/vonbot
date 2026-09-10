#!/bin/bash
# Rotate vonbot logs by COPY-TRUNCATE, keeping the inode intact.
#
# launchd holds these files open as the services' stdout/stderr (see the
# StandardOutPath/StandardErrorPath keys in the plists), so a rename-based
# rotation (newsyslog, logrotate without copytruncate) would leave the running
# process writing to the orphaned inode: the archive would keep growing while
# the new file stayed empty. Truncating in place avoids that - the process
# holds an O_APPEND fd and simply continues from offset 0.
#
# Run daily via com.vonbot.logrotate. Safe to run by hand at any time.

set -u
LOG_DIR="/Users/jeffreystark/Development/key/vonbot/logs"
MAX_BYTES=$((10 * 1024 * 1024))   # rotate anything over 10 MB
KEEP=5                            # compressed archives to retain per log

rotate() {
    local f="$1" size
    [ -f "$f" ] || return 0
    size=$(stat -f%z "$f" 2>/dev/null || echo 0)
    [ "$size" -le "$MAX_BYTES" ] && return 0

    local stamp archive
    stamp=$(date '+%Y%m%d_%H%M%S')
    archive="${f}.${stamp}.gz"

    # Copy first, then truncate in place. A few lines written between the two
    # can be lost; acceptable for logs, and the alternative loses the fd.
    if gzip -c "$f" > "$archive" 2>/dev/null; then
        : > "$f"
        echo "$(date '+%Y-%m-%d %H:%M:%S') rotated $(basename "$f") ($((size/1024/1024))MB) -> $(basename "$archive")"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') FAILED to compress $(basename "$f") - left untouched"
        rm -f "$archive"
        return 1
    fi

    # Prune oldest archives beyond KEEP
    local old
    old=$(ls -1t "${f}".*.gz 2>/dev/null | tail -n +$((KEEP + 1)))
    if [ -n "$old" ]; then
        echo "$old" | while read -r victim; do
            rm -f "$victim" && echo "  pruned $(basename "$victim")"
        done
    fi
}

for log in "$LOG_DIR"/*.log; do
    rotate "$log"
done
