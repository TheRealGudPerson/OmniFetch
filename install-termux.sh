#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${PREFIX:-}" || ! -d "$PREFIX/bin" ]]; then
    echo "This installer must be run inside Termux."
    exit 1
fi

echo "[1/3] Installing Termux system packages..."
pkg update
pkg install -y python python-pip ffmpeg aria2

echo "[2/3] Installing extraction engines..."
python -m pip install --upgrade "yt-dlp[default]" streamlink gallery-dl

echo "[3/3] Installing the omnifetch command..."
cat > "$PREFIX/bin/omnifetch" <<EOF
#!$PREFIX/bin/bash
exec "$PREFIX/bin/python" "$ROOT/omnifetch.py" "\$@"
EOF
chmod 700 "$PREFIX/bin/omnifetch"

echo
echo "OmniFetch is installed."
echo "Run: omnifetch doctor"
echo "Run: omnifetch --help"
echo
echo "For shared Android storage, run termux-setup-storage once if you have not already."
