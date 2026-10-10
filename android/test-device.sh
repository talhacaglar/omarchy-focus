#!/usr/bin/env bash
# Usage: ./android/test-device.sh /absolute/path/to/ISOLATED/pairing.json emulator-5554
# Requires a freshly cleared test app on an emulator. Never use personal pairing data.
set -euo pipefail
pairing="$(realpath "${1:?Isolated test pairing file required}")"
serial="${2:-emulator-5554}"
[[ "$serial" == emulator-* ]] || { echo 'Only an emulator is permitted.' >&2; exit 1; }
cd "$(dirname "$0")"
sdk="${ANDROID_SDK_ROOT:-$HOME/.local/share/clar-android-sdk}"
bt="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
key_dir="${XDG_CONFIG_HOME:-$HOME/.config}/clar-focus/android-signing"
mkdir -p build/test/classes build/test/dex build/test/assets
cp "$pairing" build/test/assets/pairing.json
cat > build/test/AndroidManifest.xml <<'XML'
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="dev.clar.focus.tests">
<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/>
<application android:label="Clar Focus tests"/>
<instrumentation android:name="dev.clar.focus.SyncTests" android:targetPackage="dev.clar.focus"/>
</manifest>
XML
"$bt/aapt2" link -o build/test/unsigned.apk -I "$platform" --manifest build/test/AndroidManifest.xml -A build/test/assets
javac --release 8 -encoding UTF-8 -classpath "$platform:build/classes" -d build/test/classes tests/dev/clar/focus/SyncTests.java
jar cf build/test/classes.jar -C build/test/classes .
"$bt/d8" --min-api 26 --lib "$platform" --classpath build/classes.jar --output build/test/dex build/test/classes.jar
(cd build/test/dex && zip -q -u ../unsigned.apk classes.dex)
"$bt/zipalign" -f 4 build/test/unsigned.apk build/test/aligned.apk
"$bt/apksigner" sign --ks "$key_dir/release.jks" --ks-pass "file:$key_dir/password" --ks-key-alias clar-focus --out build/test/tests.apk build/test/aligned.apk
adb -s "$serial" install -r build/test/tests.apk
adb -s "$serial" shell am force-stop dev.clar.focus
adb -s "$serial" shell am instrument -w dev.clar.focus.tests/dev.clar.focus.SyncTests
