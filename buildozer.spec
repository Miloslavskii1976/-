
[app]
title = X-BOT PHONE
package.name = xbotphone
package.domain = org.xbot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt
version = 1.1
requirements = python3==3.10.11,hostpython3==3.10.11,kivy==2.3.1,requests
orientation = portrait
fullscreen = 0
android.api = 31
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a,armeabi-v7a
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
