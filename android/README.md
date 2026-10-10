# Clar Focus for Android

[English](#english) · [Türkçe](#türkçe)

## English

Personal, offline Android companion for the desktop TUI. Android 8 or later.
Task additions, titles, notes, priorities, completion/reopening and deletions sync
in both directions. Desktop-only tags, due dates and estimates are preserved.
Pomodoro and Focus Guard remain desktop features.

No cloud service: both devices must be reachable on the same local network.
The computer runs a small HTTPS listener; it must be awake for an exchange.
Tasks can be edited on either device while disconnected. The phone retries on
opening, every 20 seconds while open, and through an Android background job
(minimum 15-minute scheduling interval; Android may delay it). A manual Sync
button is always available. Background sync is not guaranteed to be immediate.

### Build

Install Java and the official Android SDK command-line tools, then:

```sh
sdkmanager 'platforms;android-35' 'build-tools;35.0.0'
ANDROID_SDK_ROOT=/path/to/sdk ./android/build.sh
```

The default SDK location is `~/.local/share/clar-android-sdk`.
Output: `android/build/Clar-Focus.apk`. The build uses Android framework widgets
and APIs with no third-party runtime libraries. The private signing key is kept
outside the repository in `~/.config/clar-focus/android-signing/`. Back up this
directory privately: future updates need the same key to preserve app data.
Install updates over the existing app; uninstalling removes unsynced local data.

Build tool references: [D8](https://developer.android.com/tools/d8),
[apksigner](https://developer.android.com/tools/apksigner).

### Pair and run

Find the computer's Wi-Fi IPv4 address, e.g. `192.168.1.50`:

```sh
clar-focus mobile pair --host 192.168.1.50
clar-focus mobile serve --host 192.168.1.50
```

Copy the APK and the generated private
`~/.config/clar-focus/mobile-sync/clar-focus-pairing.json` to the phone over USB
or your private file-transfer method. Install the APK, tap **Bilgisayarı bağla**,
and select the pairing file. The file contains a secret: don't commit or share it.
It can be removed from the phone's Downloads after import. Do not forward the
listener port through your router. If a firewall blocks LAN access, allow only
TCP 8766 from the home subnet. No firewall changes are made automatically.

For automatic startup, use `scripts/install_mobile_sync.py --host <LAN-IP>`.
It installs a user service with the current Python interpreter, generates the
pairing file, and starts the listener. To stop:

```sh
systemctl --user disable --now clar-focus-mobile.service
```

If the computer's LAN IP changes, rerun the installer with its new address and
import the updated pairing file. The certificate, token and database identity
are preserved. A router DHCP reservation can keep the address stable.
To revoke a lost phone, stop the service, remove the `token` file, rerun pairing
and restart the service; import the new file on the trusted phone.

### Sync behavior

- TLS with an exact certificate fingerprint and a random bearer token.
- Separate stable task identities preserve existing desktop integer IDs.
- Atomic exchanges, durable operation receipts and deletion tombstones.
- Revision conflicts require an explicit choice on the phone. Neither side is
  silently overwritten. Choosing a phone edit of a deleted task creates a new task.
- Phone edits and their pending operations are written together using AtomicFile.
- APK backup is disabled so credentials and task data do not enter Android cloud backup.
- No analytics, third-party accounts, push service or remote server.

The desktop retains tombstones and receipts for offline retry safety. Large
multi-user datasets and arbitrary database restores are outside this personal
first release. Pairing to a different database is rejected to protect local work.

## Türkçe

Android 8 ve üzeri için kişisel, çevrimdışı Clar Focus uygulaması.
Görev ekleme, başlık/not/öncelik düzenleme, tamamlama, geri açma ve silme iki yönlü
eşitlenir. Bilgisayardaki etiketler, son tarihler ve süre tahminleri korunur.
Pomodoro ve Focus Guard bu sürümde bilgisayarda kalır.

Bulut hesabı gerekmez. Eşitleme sırasında bilgisayar açık olmalı ve iki cihaz
aynı yerel ağda birbirine erişebilmelidir. Bağlantı yokken değişiklikler telefonda
saklanır. Uygulama açılınca, açıkken 20 saniyede bir ve Android izin verdiğinde
arka planda yeniden denenir. Arka plan işi en az 15 dakikalık aralıkla planlanır;
Android bunu geciktirebilir. **Eşitle** düğmesiyle elle de başlatabilirsin.

APK: `android/build/Clar-Focus.apk`. Bilgisayar kurulumu:

```sh
.venv/bin/python scripts/install_mobile_sync.py --host BILGISAYARIN_WIFI_IP_ADRESI
```

APK'yı ve `~/.config/clar-focus/mobile-sync/clar-focus-pairing.json` dosyasını
USB ile telefona aktar. APK'yı kur, **Bilgisayarı bağla → Dosyayı seç** yolundan
JSON dosyasını aç. Bu dosya özel erişim anahtarı içerir; paylaşma. İçe aktardıktan
sonra İndirilenler'deki kopyasını silebilirsin. Bilgisayar IP'si değişirse kurulumu
yeni IP ile tekrarlayıp eşleştirme dosyasını yeniden seç.

Aynı görev iki cihazda değişirse uygulama iki sürümü gösterir ve hangisinin
kalacağını sorar. Bilgisayarda silinen görevin telefon sürümünü korumak yeni bir
görev oluşturur. Güncelleme APK'sını mevcut uygulamanın üzerine kur; uygulamayı
kaldırmak henüz eşitlenmemiş verileri siler.
