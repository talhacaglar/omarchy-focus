#!/usr/bin/env bash
# Minimal native Android build using official SDK tools; no remote app dependencies.
set -euo pipefail
cd "$(dirname "$0")"
sdk="${ANDROID_SDK_ROOT:-$HOME/.local/share/clar-android-sdk}"
bt="$sdk/build-tools/35.0.0"
platform="$sdk/platforms/android-35/android.jar"
key_dir="${XDG_CONFIG_HOME:-$HOME/.config}/clar-focus/android-signing"
for tool in "$bt/aapt2" "$bt/d8" "$bt/zipalign" "$bt/apksigner"; do
    [[ -x "$tool" ]] || { echo "Missing Android SDK tool: $tool" >&2; exit 1; }
done
mkdir -p build/classes build/dex build/gen
"$bt/aapt2" compile --dir res -o build/resources.zip
"$bt/aapt2" link -o build/resources.apk -I "$platform" --manifest AndroidManifest.xml --java build/gen build/resources.zip
mapfile -t sources < <(find src build/gen -name '*.java' | sort)
javac --release 8 -encoding UTF-8 -classpath "$platform" -d build/classes "${sources[@]}"
jar cf build/classes.jar -C build/classes .
"$bt/d8" --release --min-api 26 --lib "$platform" --output build/dex build/classes.jar
cp build/resources.apk build/unsigned.apk
(cd build/dex && zip -q -u ../unsigned.apk classes*.dex)
"$bt/zipalign" -f 4 build/unsigned.apk build/aligned.apk
# Keep the private signing identity across builds so APK updates retain local data.
mkdir -p "$key_dir"
chmod 700 "$key_dir"
if [[ ! -f "$key_dir/release.jks" ]]; then
    umask 077
    openssl rand -hex 32 > "$key_dir/password"
    keytool -genkeypair -keystore "$key_dir/release.jks" -storepass:file "$key_dir/password" \
        -keypass:file "$key_dir/password" -alias clar-focus -keyalg RSA -keysize 3072 \
        -validity 10000 -dname 'CN=Clar Focus Personal'
fi
"$bt/apksigner" sign --ks "$key_dir/release.jks" --ks-pass "file:$key_dir/password" \
    --ks-key-alias clar-focus --out build/Clar-Focus.apk build/aligned.apk
"$bt/apksigner" verify --verbose build/Clar-Focus.apk
printf 'APK: %s/android/build/Clar-Focus.apk\n' "$(dirname "$PWD")"
