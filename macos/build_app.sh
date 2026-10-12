#!/bin/bash
# Build Spec-to-Test.app — the app in its own window, for this checkout.
#
# Usage: macos/build_app.sh [DESTINATION_DIR]   (default: ~/Applications)
#
# The app runs macos/start.sh from this folder, so rebuild it if you move the
# repository or recreate .venv with another Python. Closing the window (or ⌘Q)
# stops the server.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-$HOME/Applications}"
APP="$DEST_DIR/Spec-to-Test.app"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

chmod +x "$ROOT/macos/start.sh"
echo "Preparing .venv and the Automation toolchain (first time: installs dependencies)…"
"$ROOT/macos/start.sh" --setup-only

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# A copy of the framework's GUI interpreter (python.org and Homebrew builds
# ship one in Python.app). Running it from inside this bundle makes macOS treat
# the process as Spec-to-Test. Without it the app still works, as "Python".
gui_python="$("$ROOT/.venv/bin/python" -c '
import pathlib, sys
base = pathlib.Path(sys.base_prefix)
print(base / "Resources/Python.app/Contents/MacOS/Python")
')"
if [[ -x "$gui_python" ]]; then
    cp "$gui_python" "$APP/Contents/MacOS/python"
else
    echo "Note: no Python.app interpreter in this Python; the Dock will show it as Python." >&2
fi

# The bundle's entry point. It remembers where node is (for the Automation tab),
# because apps opened from Finder do not get the shell's PATH.
printf -v root_q '%q' "$ROOT"
node_line=""
if node_bin="$(command -v node)"; then
    printf -v node_q '%q' "$node_bin"
    node_line="export SPEC_TO_TEST_NODE=$node_q"
else
    echo "Note: Node.js not found; the Automation tab will ask for it." >&2
fi
cat >"$APP/Contents/MacOS/Spec-to-Test" <<EOF
#!/bin/bash
here="\$(cd "\$(dirname "\$0")" && pwd)"
log="\$HOME/Library/Logs/Spec-to-Test/server.log"
mkdir -p "\$(dirname "\$log")"
exec >>"\$log" 2>&1
[[ -x "\$here/python" ]] && export SPEC_TO_TEST_PYTHON="\$here/python"
export SPEC_TO_TEST_ICON="\$here/../Resources/AppIcon.png"
$node_line
exec $root_q/macos/start.sh
EOF
chmod +x "$APP/Contents/MacOS/Spec-to-Test"

# Icon.
"$ROOT/.venv/bin/python" "$ROOT/macos/make_icon.py" "$APP/Contents/Resources/AppIcon.png"
iconset="$WORK/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$APP/Contents/Resources/AppIcon.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$APP/Contents/Resources/AppIcon.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$APP/Contents/Resources/AppIcon.icns"

version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")"
cat >"$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key><string>en</string>
	<key>CFBundleDisplayName</key><string>Spec-to-Test</string>
	<key>CFBundleExecutable</key><string>Spec-to-Test</string>
	<key>CFBundleIconFile</key><string>AppIcon</string>
	<key>CFBundleIdentifier</key><string>io.github.antonplotnikov.spec-to-test</string>
	<key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
	<key>CFBundleName</key><string>Spec-to-Test</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>$version</string>
	<key>CFBundleVersion</key><string>$version</string>
	<key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
	<key>LSMinimumSystemVersion</key><string>11.0</string>
	<key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Ad hoc signature (required to run on Apple silicon; not notarized).
codesign --force --deep --sign - "$APP"
touch "$APP"
echo "Built $APP"
echo "Open it from Finder, Launchpad, or Spotlight (\"Spec-to-Test\")."
