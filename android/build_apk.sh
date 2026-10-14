#!/usr/bin/env bash
# Builds the HD Agent APK with the plain Android SDK tools (aapt2, javac, d8, zipalign, apksigner) — no Gradle.
set -euo pipefail
cd "$(dirname "$0")"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/android-sdk-linux}}"
BT="$(ls -d "$SDK"/build-tools/* | sort -V | tail -1)"
JAR="$(ls -d "$SDK"/platforms/android-* | sort -V | tail -1)/android.jar"
URL="${APP_URL:-${PUBLIC_URL:-}}"
[ -n "$URL" ] || { echo "APP_URL/PUBLIC_URL is not set"; exit 1; }
URL="${URL%/}/"
VCODE="${APP_VERSION_CODE:-$(date -u +%y%m%d%H)}"
VNAME="${APP_VERSION:-1.0.$VCODE}"
echo "SDK=$SDK BT=$BT JAR=$JAR URL=$URL version=$VNAME ($VCODE)"

rm -rf build dist && mkdir -p build/gen build/classes build/dex dist
sed -i "s#__APP_URL__#${URL}#" res/values/strings.xml

"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -o build/unsigned.apk -I "$JAR" --manifest AndroidManifest.xml -R build/res.zip --java build/gen \
  --min-sdk-version 24 --target-sdk-version 34 --version-code "$VCODE" --version-name "$VNAME" --auto-add-overlay
javac -encoding UTF-8 -source 1.8 -target 1.8 -nowarn -classpath "$JAR" -d build/classes \
  $(find src build/gen -name '*.java')
"$BT/d8" --release --min-api 24 --lib "$JAR" --output build/dex $(find build/classes -name '*.class')
( cd build/dex && if [ -x "$BT/aapt" ]; then "$BT/aapt" add ../unsigned.apk classes.dex; else jar -u -f ../unsigned.apk classes.dex; fi )
"$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk

KS=build/release.jks
if [ -n "${APK_KEYSTORE_B64:-}" ]; then
  echo "$APK_KEYSTORE_B64" | base64 -d > "$KS"
else
  echo "WARNING: APK_KEYSTORE_B64 not set — using a throwaway key (users will need to uninstall before updating)"
  APK_KS_PASS="hdagent-temp-pass"
  keytool -genkeypair -keystore "$KS" -storepass "$APK_KS_PASS" -keypass "$APK_KS_PASS" -alias hdagent \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=HD Agent" >/dev/null
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:${APK_KS_PASS}" --key-pass "pass:${APK_KS_PASS}" --ks-key-alias hdagent \
  --out dist/HD-Agent.apk build/aligned.apk
"$BT/apksigner" verify dist/HD-Agent.apk
ls -la dist/
