#!/bin/sh
# Setup: install deps and bind Super to sway-overview in Sway.
set -e
HERE="$(dirname "$(readlink -f "$0")")"
BIN="$HERE/sway-overview"
chmod +x "$BIN"

echo "== installing dependencies =="
sudo apt-get update -qq
sudo apt-get install -y grim python3-gi gir1.2-gtk-3.0 gir1.2-gtk-layer-shell-0.1

CONFIG="$HOME/.config/sway/config"
if [ -f "$CONFIG" ] && ! grep -q "sway-overview" "$CONFIG"; then
  echo "== adding Super binding to sway config =="
  cat >> "$CONFIG" <<EOF

# sway-overview: Super-key window exposé + search + app grid
bindsym Mod4 exec $BIN
EOF
  swaymsg reload 2>/dev/null || true
  echo "bound Mod4 (Super) to sway-overview; config reloaded."
elif grep -q "sway-overview" "$CONFIG" 2>/dev/null; then
  echo "sway config already references sway-overview; skipping."
else
  echo "no sway config at $CONFIG — add this line manually:"
  echo "  bindsym Mod4 exec $BIN"
fi

echo "done — press Super to open the overview."
