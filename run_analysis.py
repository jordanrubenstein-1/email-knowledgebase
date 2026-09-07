#!/usr/bin/env python3
import subprocess
import sys

result = subprocess.run([sys.executable, 'scripts/analysis/analyze_send_volumes.py'],
                       capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(result.stderr, file=sys.stderr)
sys.exit(result.returncode)
