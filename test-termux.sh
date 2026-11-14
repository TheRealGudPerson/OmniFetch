#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$(dirname -- "$0")"
python -m compileall -q omnifetch.py omnifetch tests
python -m unittest discover -s tests -v
