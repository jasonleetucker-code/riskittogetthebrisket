#!/usr/bin/env python3
"""Small follow-up patch for public FFPC standings with division label rows."""

from pathlib import Path

path = Path("src/platforms/ffpc/parser.py")
text = path.read_text(encoding="utf-8")
start = text.index("def _find_tables(")
end = text.index("\n\ndef _query_id", start)
section = text[start:end]
old = '        keys = {k for k in rows[0] if not k.startswith("_")}\n'
new = '''        keys = {
            key
            for row in rows
            for key in row
            if not key.startswith("_")
        }
'''
if old not in section and new not in section:
    raise RuntimeError("missing _find_tables key-discovery anchor")
if old in section:
    section = section.replace(old, new, 1)
    text = text[:start] + section + text[end:]
    path.write_text(text, encoding="utf-8")
