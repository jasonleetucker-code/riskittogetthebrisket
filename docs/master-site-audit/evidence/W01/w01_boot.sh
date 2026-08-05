#!/bin/bash
SP=/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad
cd /home/user/riskittogetthebrisket
export ALLOW_DEFAULT_LOGIN_DEV=1 RATE_LIMIT_BYPASS_IPS=127.0.0.1 PLAYWRIGHT_BROWSERS_PATH=/tmp/no-pw-browsers
export E2E_TEST_MODE=1 UPTIME_CHECK_ENABLED=false E2E_TEST_USERNAME=e2e-test-user PYTHONUNBUFFERED=1 W01_PORT=8001
LOG=$1; shift
for kv in "$@"; do export "$kv"; done
exec .venv/bin/python $SP/w01_launcher.py > $LOG 2>&1
