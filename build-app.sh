#!/usr/bin/env bash
# Builds nam2zoom-mac in release mode and wraps it into a double-clickable
# nam2zoom.app bundle (ad-hoc signed for local use; not notarized).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

swift build -c release

bin="$(swift build -c release --show-bin-path)/nam2zoomMac"
resource_bundle="$(swift build -c release --show-bin-path)/nam2zoom-mac_nam2zoomMac.bundle"

app="$here/nam2zoom.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"

cp "$bin" "$app/Contents/MacOS/nam2zoom"
if [ -d "$resource_bundle" ]; then
  cp -R "$resource_bundle" "$app/Contents/Resources/"
fi
if [ -f "$here/AppIcon.icns" ]; then
  cp "$here/AppIcon.icns" "$app/Contents/Resources/AppIcon.icns"
fi

cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>nam2zoom</string>
	<key>CFBundleDisplayName</key>
	<string>nam2zoom</string>
	<key>CFBundleIdentifier</key>
	<string>com.nam2zoom.mac</string>
	<key>CFBundleVersion</key>
	<string>0.1</string>
	<key>CFBundleShortVersionString</key>
	<string>0.1</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleExecutable</key>
	<string>nam2zoom</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$app"

echo "Built: $app"
