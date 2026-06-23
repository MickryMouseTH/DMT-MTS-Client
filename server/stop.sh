#!/usr/bin/env bash
#
# Stop the MTS Monitoring API server started by start.sh.
#
set -euo pipefail

cd "$(dirname "$0")"

PIDFILE="server.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "No PID file found ($PIDFILE). Server does not appear to be running."
    exit 0
fi

PID="$(cat "$PIDFILE" 2>/dev/null || true)"

if [ -z "${PID}" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "Process $PID not running. Removing stale PID file."
    rm -f "$PIDFILE"
    exit 0
fi

echo "Stopping MTS Server (PID $PID)..."
kill "$PID"

# Wait up to ~10s for a graceful shutdown, then force-kill.
for _ in $(seq 1 20); do
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

if kill -0 "$PID" 2>/dev/null; then
    echo "Graceful stop timed out; sending SIGKILL."
    kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PIDFILE"
echo "MTS Server stopped."
