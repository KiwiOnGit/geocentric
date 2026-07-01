#!/bin/bash
set -e

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${SCRIPT_DIR}"
BUILD_DIR="${APP_DIR}/Geocentric.app"
CONTENTS_DIR="${BUILD_DIR}/Contents"
MAC_OS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
INSTALLER_TEMP="${APP_DIR}/Geocentric_Installer_Temp"
BUILD_SUPPORT_DIR="${APP_DIR}/.build"
FAST_INTENT_OBJECT="${BUILD_SUPPORT_DIR}/FastIntentClassifier.o"
trap 'rm -rf "${BUILD_SUPPORT_DIR}"' EXIT

echo "=== 1. Creating App Bundle Directory Structure ==="
rm -rf "${BUILD_DIR}"
rm -rf "${BUILD_SUPPORT_DIR}"
mkdir -p "${MAC_OS_DIR}"
mkdir -p "${RESOURCES_DIR}"
mkdir -p "${BUILD_SUPPORT_DIR}"

echo "=== 2. Copying Compiled Binary ==="
echo "Compiling C++ helpers..."
clang++ -c -O3 "${APP_DIR}/FastIntentClassifier.cpp" -o "${FAST_INTENT_OBJECT}"

echo "Compiling Geocentric desktop host..."
swiftc -sdk /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk \
       -parse-as-library \
       -import-objc-header "${APP_DIR}/Geocentric-Bridging-Header.h" \
       "${APP_DIR}/main.swift" \
       "${APP_DIR}/Models.swift" \
       "${APP_DIR}/DesktopServer.swift" \
       "${APP_DIR}/OllamaManager.swift" \
       "${APP_DIR}/NativeAPIClient.swift" \
       "${APP_DIR}/NativeAppModel.swift" \
       "${APP_DIR}/AppUpdater.swift" \
       "${APP_DIR}/UIStyles.swift" \
       "${APP_DIR}/AppDelegate.swift" \
       "${APP_DIR}/Views/RootView.swift" \
       "${APP_DIR}/Views/SidebarView.swift" \
       "${APP_DIR}/Views/ConversationView.swift" \
       "${APP_DIR}/Views/ModelManagerView.swift" \
       "${APP_DIR}/Views/SettingsView.swift" \
       "${FAST_INTENT_OBJECT}" \
       -lc++ \
       -o "${APP_DIR}/Geocentric"
cp "${APP_DIR}/Geocentric" "${MAC_OS_DIR}/Geocentric"
chmod +x "${MAC_OS_DIR}/Geocentric"

echo "=== 3. Creating App Icon (icns) ==="
PNG_ICON="${PROJECT_DIR}/geocentric/web/appicon.png"
if [ -f "${PNG_ICON}" ]; then
    echo "Found app icon PNG. Generating icns set..."
    ICONSET_DIR="${APP_DIR}/appicon.iconset"
    rm -rf "${ICONSET_DIR}"
    mkdir -p "${ICONSET_DIR}"
    
    # Scale PNG to standard macOS icon sizes
    sips -z 16 16     "${PNG_ICON}" --out "${ICONSET_DIR}/icon_16x16.png" > /dev/null 2>&1
    sips -z 32 32     "${PNG_ICON}" --out "${ICONSET_DIR}/icon_16x16@2x.png" > /dev/null 2>&1
    sips -z 32 32     "${PNG_ICON}" --out "${ICONSET_DIR}/icon_32x32.png" > /dev/null 2>&1
    sips -z 64 64     "${PNG_ICON}" --out "${ICONSET_DIR}/icon_32x32@2x.png" > /dev/null 2>&1
    sips -z 128 128   "${PNG_ICON}" --out "${ICONSET_DIR}/icon_128x128.png" > /dev/null 2>&1
    sips -z 256 256   "${PNG_ICON}" --out "${ICONSET_DIR}/icon_128x128@2x.png" > /dev/null 2>&1
    sips -z 256 256   "${PNG_ICON}" --out "${ICONSET_DIR}/icon_256x256.png" > /dev/null 2>&1
    sips -z 512 512   "${PNG_ICON}" --out "${ICONSET_DIR}/icon_256x256@2x.png" > /dev/null 2>&1
    sips -z 512 512   "${PNG_ICON}" --out "${ICONSET_DIR}/icon_512x512.png" > /dev/null 2>&1
    sips -z 1024 1024 "${PNG_ICON}" --out "${ICONSET_DIR}/icon_512x512@2x.png" > /dev/null 2>&1
    
    # Convert iconset directory to native Apple icns format
    iconutil -c icns "${ICONSET_DIR}" -o "${RESOURCES_DIR}/appicon.icns"
    rm -rf "${ICONSET_DIR}"
    echo "Icon generation completed successfully."
else
    echo "Warning: appicon.png not found. App bundle will lack a custom icon file."
fi

echo "=== 4. Creating Info.plist ==="
cat <<EOF > "${CONTENTS_DIR}/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Geocentric</string>
    <key>CFBundleIconFile</key>
    <string>appicon.icns</string>
    <key>CFBundleIdentifier</key>
    <string>com.geocentric.agentos</string>
    <key>CFBundleName</key>
    <string>Geocentric</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSLocalNetworkUsageDescription</key>
    <string>Geocentric can host its web UI on your local Wi-Fi network when you choose Local Wi-Fi at startup.</string>
    <key>NSAccessibilityUsageDescription</key>
    <string>Geocentric requires accessibility access to analyze active window locations and track code editor selection contexts.</string>
    <key>NSScreenCaptureUsageDescription</key>
    <string>Geocentric requires screen capture access to analyze visual mockups and layout layouts for front-end agents.</string>
</dict>
</plist>
EOF

echo "=== 5. Copying Python Source components into Bundle Resources ==="
# Copies the backend server package and requirements into resources to ensure a fully self-contained bundle
cp -R "${PROJECT_DIR}/geocentric" "${RESOURCES_DIR}/"
cp "${PROJECT_DIR}/requirements.txt" "${RESOURCES_DIR}/"
if [ -d "${PROJECT_DIR}/scripts" ]; then
    cp -R "${PROJECT_DIR}/scripts" "${RESOURCES_DIR}/"
fi
if [ -d "${PROJECT_DIR}/templates" ]; then
    cp -R "${PROJECT_DIR}/templates" "${RESOURCES_DIR}/"
fi
if [ -d "${PROJECT_DIR}/skills" ]; then
    cp -R "${PROJECT_DIR}/skills" "${RESOURCES_DIR}/"
fi
find "${RESOURCES_DIR}" -name ".DS_Store" -delete
find "${RESOURCES_DIR}" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${RESOURCES_DIR}" -name "*.pyc" -delete

echo "=== 6. Signing App Bundle ==="
if [ -n "${GEOCENTRIC_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --deep --options runtime --timestamp --sign "${GEOCENTRIC_CODESIGN_IDENTITY}" "${BUILD_DIR}"
else
    codesign --force --deep --sign - "${BUILD_DIR}"
    echo "No GEOCENTRIC_CODESIGN_IDENTITY set; applied an ad-hoc local signature."
fi

echo "=== 7. Packing Drag-and-Drop DMG Installer ==="
rm -rf "${INSTALLER_TEMP}"
mkdir -p "${INSTALLER_TEMP}"

# Copy App to installer folder
cp -R "${BUILD_DIR}" "${INSTALLER_TEMP}/"

# Create symbolic link to /Applications for standard drag-and-drop workflow
ln -s /Applications "${INSTALLER_TEMP}/Applications"

# Compile final dmg using Apple hdiutil
DMG_FILE="${PROJECT_DIR}/Geocentric.dmg"
rm -f "${DMG_FILE}"
hdiutil create -volname "Geocentric Installer" \
               -srcfolder "${INSTALLER_TEMP}" \
               -ov -format UDZO \
               "${DMG_FILE}"

if [ -n "${GEOCENTRIC_CODESIGN_IDENTITY:-}" ]; then
    codesign --force --timestamp --sign "${GEOCENTRIC_CODESIGN_IDENTITY}" "${DMG_FILE}"
fi

if [ -n "${GEOCENTRIC_NOTARY_PROFILE:-}" ]; then
    echo "=== 7.5. Notarizing DMG ==="
    xcrun notarytool submit "${DMG_FILE}" \
        --keychain-profile "${GEOCENTRIC_NOTARY_PROFILE}" \
        --wait
    xcrun stapler staple "${DMG_FILE}"
fi

echo "=== 8. Cleaning Up Temporary Installer Build Items ==="
rm -rf "${INSTALLER_TEMP}"
rm -rf "${BUILD_SUPPORT_DIR}"

echo "=== Packaging completed successfully! ==="
echo "Output distribution file: ${DMG_FILE}"
