#!/bin/bash
# Lifecycle Dashboard Startup Script
# Starts all lifecycle dashboards (cover page + 5 brand dashboards)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/tmp/lifecycle_dashboards"
mkdir -p "$LOG_DIR"

# Find streamlit
if command -v streamlit &> /dev/null; then
    STREAMLIT="streamlit"
elif command -v uv &> /dev/null; then
    STREAMLIT="uv run streamlit"
else
    echo "Error: streamlit not found. Run: pip install streamlit"
    exit 1
fi

echo "Starting Lifecycle Dashboards..."

start_dashboard() {
    local name=$1
    local file=$2
    local port=$3
    local log="$LOG_DIR/${name}.log"

    # Kill anything already on this port
    lsof -ti:$port | xargs kill -9 2>/dev/null

    nohup $STREAMLIT run "$SCRIPT_DIR/$file" --server.port $port --server.headless true > "$log" 2>&1 &
    echo "  ✓ $name → http://localhost:$port  (log: $log)"
}

start_dashboard "cover"      "cover_dashboard.py"          8500
start_dashboard "canvas-map" "canvas_map_dashboard.py"    8507
start_dashboard "hav"    "hav_lifecycle_dashboard.py" 8504
start_dashboard "bur"    "lifecycle_dashboard.py"    8502
start_dashboard "cz"     "cz_lifecycle_dashboard.py" 8503
start_dashboard "id"     "id_lifecycle_dashboard.py" 8505
start_dashboard "stf"    "stf_lifecycle_dashboard.py" 8506
start_dashboard "ti"     "ti_lifecycle_dashboard.py" 8510

echo ""
echo "All dashboards starting — open http://localhost:8500 in your browser."
echo "  Canvas Map: http://localhost:8507"
echo "Allow ~10 seconds for first load while Snowflake queries warm up."
echo ""
echo "To stop all dashboards: bash scripts/stop_dashboards.sh"
