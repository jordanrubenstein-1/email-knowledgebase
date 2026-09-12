#!/bin/bash
# Stop all lifecycle dashboards

for port in 8500 8502 8503 8504 8505 8506 8510; do
    pids=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        echo "  ✓ Stopped dashboard on port $port"
    fi
done
echo "All dashboards stopped."
