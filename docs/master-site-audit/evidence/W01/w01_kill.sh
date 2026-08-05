#!/bin/bash
for p in $(pgrep -f 'w01_launcher'); do
  if [ "$p" != "$$" ] && [ "$p" != "$PPID" ]; then
    grep -q "w01_launcher.py" /proc/$p/cmdline 2>/dev/null && head -c 40 /proc/$p/cmdline | grep -q python && kill $p && echo "killed $p"
  fi
done
