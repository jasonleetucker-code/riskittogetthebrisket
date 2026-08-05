#!/bin/sh
# W17-F003: prove ROS values never reach the dynasty contract or trade math.
set -e
cd "$(dirname "$0")/../../../.."
echo "--- 1. ROS-prefixed keys anywhere in the live /api/data contract:"
curl -s -b /tmp/audit-cookies.txt 'http://127.0.0.1:8000/api/data?view=app' \
  | .venv/bin/python -c '
import json, re, sys
pat = re.compile(r"^(ros[A-Z]|ros_|restOfSeason|teamRos)")
hits = set()
def walk(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if pat.match(str(k)):
                hits.add(p + "." + k)
            walk(v, p + "." + k)
    elif isinstance(o, list):
        for v in o[:2]:
            walk(v, p + "[]")
walk(json.load(sys.stdin))
print(sorted(hits) or "NONE")
'
echo "--- 2. src.ros imports inside the value pipeline (expect no output):"
grep -rn 'src\.ros\b' src/api/data_contract.py src/trade/ src/canonical/ || echo "NONE"
echo "--- 3. write paths under src/ros that escape ROS_DATA_DIR (expect no output):"
grep -rn 'write_text\|to_csv' --include='*.py' src/ros/ | grep -v ROS_DATA_DIR | grep -v 'agg_dir\|target\|archive\|index_path\|playoff_path\|champ_path\|run_path' || echo "NONE"
