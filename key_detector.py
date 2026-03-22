#!/usr/bin/env python3
"""
キーコード診断ツール
マイクキー・その他のキーを押して、どんなコードが届くか確認する
Ctrl+C で終了
"""
from pynput import keyboard
from AppKit import NSEvent
from Foundation import NSRunLoop, NSDate

print("=" * 50)
print("キーコード診断ツール")
print("マイクキー（Fn なし）を押してください")
print("Ctrl+C で終了")
print("=" * 50)

def on_press(key):
    try:
        print(f"[pynput] pressed  : {key!r}  vk={key.vk}")
    except AttributeError:
        print(f"[pynput] pressed  : {key!r}")

def on_release(key):
    try:
        print(f"[pynput] released : {key!r}  vk={key.vk}")
    except AttributeError:
        print(f"[pynput] released : {key!r}")

def on_media(event):
    t = event.type()
    s = event.subtype()
    if s == 8:
        d1 = event.data1()
        kc    = (d1 & 0xFFFF0000) >> 16
        state = (d1 & 0xFF00) >> 8
        down  = (state == 0x0A)
        print(f"[NSEvent media]    keyCode={kc} (0x{kc:02X})  down={down}")
    else:
        print(f"[NSEvent sys]      type={t}  subtype={s}  data1={event.data1()}")

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(1 << 14, on_media)

rl = NSRunLoop.currentRunLoop()
try:
    while True:
        rl.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
except KeyboardInterrupt:
    pass
finally:
    NSEvent.removeMonitor_(monitor)
    listener.stop()
    print("\n終了しました")
