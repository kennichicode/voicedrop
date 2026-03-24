#!/usr/bin/env python3
"""VoiceDrop — Click-to-paste voice input for macOS"""

import threading, subprocess, time, json, traceback, sys, multiprocessing, os, tempfile, re as _re
import ctypes, ctypes.util
import Quartz as _Q
from datetime import datetime
from pathlib import Path
import numpy as np
import sounddevice as sd
import mlx_whisper
from pynput import keyboard, mouse
import rumps
import objc
from PyObjCTools import AppHelper
from Foundation import NSObject, NSAttributedString
from AppKit import (NSPanel, NSColor, NSView, NSBezierPath, NSFont,
                    NSFontAttributeName, NSForegroundColorAttributeName,
                    NSFloatingWindowLevel, NSWorkspace, NSImage, NSBitmapImageRep)

# ── Waveform icon ────────────────────────────────
_WAVEFORM_PNG_PATH = None

def _build_waveform_png():
    """DAW風縦バー波形をPNGファイルとして生成しパスを返す（アタック→減衰）"""
    w, h = 28.0, 18.0
    bars = [3, 7, 12, 16, 14, 10, 7, 5, 3]
    bar_w, gap, cy = 2.0, 1.0, h / 2.0
    img = NSImage.alloc().initWithSize_((w, h))
    img.lockFocus()
    NSColor.clearColor().set()
    NSBezierPath.fillRect_(((0.0, 0.0), (w, h)))
    NSColor.blackColor().setFill()
    x = 1.0
    for bh in bars:
        bh = float(bh)
        r = ((x, cy - bh / 2.0), (bar_w, bh))
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 0.6, 0.6).fill()
        x += bar_w + gap
    img.unlockFocus()
    tiff = img.TIFFRepresentation()
    bitmap = NSBitmapImageRep.imageRepWithData_(tiff)
    png_data = bitmap.representationUsingType_properties_(4, None)  # 4 = PNG
    path = os.path.join(tempfile.gettempdir(), "voicedrop_waveform.png")
    with open(path, 'wb') as f:
        f.write(bytes(png_data))
    return path


# ── Audio / Model config ─────────────────────────
MLX_MODEL_REPO = "mlx-community/whisper-large-v3-turbo"
SAMPLE_RATE = 16000
LANGUAGE    = "ja"
MAX_RECORDING_SECONDS = 5 * 60
TRANSCRIBE_CHUNK_SECONDS = 60
FILE_SAVE_MINUTES_THRESHOLD = 3 * 60

# ── Hotkey presets ───────────────────────────────
MIC_VK = 176   # MacBook Air M1 マイクキー (Fn なし) の仮想キーコード

HOTKEY_OPTIONS = [
    ("右 Option キー  ⭐",      "right_option"),
    ("右 ⌘ キー  ⭐",          "right_cmd"),
    ("Ctrl+Shift+Space",      "ctrl_shift_space"),
    ("Option+Space",          "opt_space"),
    ("🎙  Mic Key  (Fn不要)",  "mic_key"),
    ("F5  (Fn+マイク)",        "f5"),
    ("F4",                    "f4"),
    ("F6",                    "f6"),
]

# ── Config / app support files ───────────────────
APP_SUPPORT_DIR = Path(tempfile.gettempdir()) / "VoiceDrop"
LEGACY_CONFIG_PATH = Path.home() / ".voice-type" / "config.json"
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
TRANSCRIPT_DIR = Path.home() / "Desktop" / "VoiceDrop Transcripts"
HISTORY_PATH = Path.home() / ".voice-type" / "history.json"
HISTORY_MAX = 30
DEFAULT_CFG = {"hotkey": "right_option"}
config: dict = {}
INSTANCE_LOCK_PATH = APP_SUPPORT_DIR / "app.lock"
instance_lock_fp = None


def log_exception(prefix):
    print(f"[ERROR] {prefix}\n{traceback.format_exc()}", flush=True)


def notify(title, subtitle="", message=""):
    AppHelper.callAfter(rumps.notification, title, subtitle, message, False)


def acquire_single_instance_lock():
    global instance_lock_fp
    INSTANCE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    instance_lock_fp = INSTANCE_LOCK_PATH.open("w")
    try:
        import fcntl
        fcntl.flock(instance_lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        instance_lock_fp.write(str(os.getpid()) if 'os' in globals() else "")
        instance_lock_fp.flush()
        return True
    except Exception:
        return False

def load_config():
    global config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists() and LEGACY_CONFIG_PATH.exists():
        try:
            CONFIG_PATH.write_text(LEGACY_CONFIG_PATH.read_text())
        except Exception:
            pass
    if CONFIG_PATH.exists():
        try:
            config = {**DEFAULT_CFG, **json.loads(CONFIG_PATH.read_text())}
        except Exception:
            config = DEFAULT_CFG.copy()
    else:
        config = DEFAULT_CFG.copy()
        CONFIG_PATH.write_text(json.dumps(config, indent=2))

def save_config():
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

# ── History ───────────────────────────────────────
def load_history() -> list:
    try:
        if HISTORY_PATH.exists():
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def save_to_history(text: str):
    history = load_history()
    history.insert(0, {
        "text": text,
        "ts": datetime.now().strftime("%m/%d %H:%M"),
    })
    history = history[:HISTORY_MAX]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

# ── State ────────────────────────────────────────
model_ready    = threading.Event()
is_recording   = False
is_transcribing = False
audio_buffer   = []
audio_level    = 0.0
stream         = None
hotkey_active  = False
current_keys   = set()
recording_timer = None
recording_started_at = 0.0
stop_lock = threading.Lock()
is_paused      = False
_press_start_time: float = 0.0
_press_was_start: bool = False   # このプレスで録音を開始した → リリース時に無視
_last_pause_press: float = 0.0   # 一時停止プレスの時刻（ダブルプレス検出用）
_DOUBLE_PRESS_SEC = 0.4          # ダブルプレス判定時間（秒）
_RIGHT_OPTION_VK   = 61          # Right Option の仮想キーコード
_active_event_tap  = None        # CGEventTap 参照保持
_tap_cb_ref        = None        # ctypes callback GC防止
saved_mouse_x  = 0.0   # Quartz coords for click
saved_mouse_y  = 0.0
saved_appkit_x = 0.0   # AppKit coords for overlay
saved_appkit_y = 0.0
saved_frontmost_app_name = ""
latest_click_x = 0.0
latest_click_y = 0.0
latest_click_app_name = ""
click_target_ready = False
pending_paste_armed = False
synthetic_click_in_progress = False


# ══════════════════════════════════════════════════
#  Mic cursor overlay  (NSPanel floating near cursor)
# ══════════════════════════════════════════════════
_OVERLAY_W = 84
_OVERLAY_H = 30

class _MicBgView(NSView):
    """Dark pill with red dot + REC label."""
    def drawRect_(self, dirtyRect):
        objc.super(_MicBgView, self).drawRect_(dirtyRect)
        bounds = self.bounds()
        w = bounds.size.width
        h = bounds.size.height

        # dark pill background
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, h / 2, h / 2)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.06, 0.06, 0.06, 0.90).setFill()
        path.fill()

        dot_d = 8
        dot_x = 14
        dot_y = (h - dot_d) / 2
        dot_path = NSBezierPath.bezierPathWithOvalInRect_(
            ((dot_x, dot_y), (dot_d, dot_d)))

        if is_paused:
            # 黄色ドット + ⏸
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                1.0, 0.78, 0.0, 1.0).setFill()
            dot_path.fill()
            label = "⏸"
            label_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                1.0, 0.85, 0.2, 1.0)
        else:
            # 赤ドット + REC
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.95, 0.22, 0.22, 1.0).setFill()
            dot_path.fill()
            label = "REC"
            label_color = NSColor.whiteColor()

        try:
            attrs = {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(12),
                NSForegroundColorAttributeName: label_color,
            }
            s = NSAttributedString.alloc().initWithString_attributes_(label, attrs)
            sz = s.size()
            x = dot_x + dot_d + 7
            y = (h - sz.height) / 2
            s.drawAtPoint_((x, y))
        except Exception:
            pass


class MicOverlay(NSObject):
    """Show/hide a floating mic badge near the cursor."""

    def init(self):
        self = objc.super(MicOverlay, self).init()
        if self is None:
            return None
        self._panel = None
        self._px    = 0.0
        self._py    = 0.0
        return self

    @objc.python_method
    def show_near(self, appkit_x, appkit_y):
        """Thread-safe: dispatch show to main thread."""
        # Offset: 18px right, 48px down (y decreases = visually down in AppKit)
        self._px = appkit_x + 18
        self._py = appkit_y - 58
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            b'_show:', None, False)

    @objc.python_method
    def hide(self):
        """Thread-safe: dispatch hide to main thread."""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            b'_hide:', None, False)

    def _show_(self, _):
        if self._panel is None:
            rect = (0, 0, _OVERLAY_W, _OVERLAY_H)
            # styleMask=0 → borderless; backing=2 → NSBackingStoreBuffered
            self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, 0, 2, False)
            self._panel.setBackgroundColor_(NSColor.clearColor())
            self._panel.setOpaque_(False)
            self._panel.setLevel_(NSFloatingWindowLevel + 2)
            self._panel.setIgnoresMouseEvents_(True)
            self._panel.setHasShadow_(False)
            # show on all Spaces
            self._panel.setCollectionBehavior_(1 << 0)  # CanJoinAllSpaces
            view = _MicBgView.alloc().initWithFrame_(rect)
            self._panel.setContentView_(view)

        self._panel.setFrameOrigin_((self._px, self._py))
        self._panel.orderFront_(None)

    def _hide_(self, _):
        if self._panel:
            self._panel.orderOut_(None)

    @objc.python_method
    def refresh(self):
        """一時停止/再開後に再描画"""
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            b'_refresh:', None, False)

    def _refresh_(self, _):
        if self._panel:
            self._panel.contentView().setNeedsDisplay_(True)
            self._panel.display()


overlay_ctrl: MicOverlay = None   # initialized in __main__


# ══════════════════════════════════════════════════
#  Menu Bar App  (clean, minimal UI)
# ══════════════════════════════════════════════════
# ── Status item single-click handler ──────────────────────────────────────────
class _StatusClickHandler(NSObject):
    """録音中: クリック = 一時停止/再開。非録音中: メニューを表示。"""

    def init(self):
        self = objc.super(_StatusClickHandler, self).init()
        self._si = None
        return self

    @objc.python_method
    def attach(self, status_item):
        self._si = status_item
        btn = status_item.button()
        btn.setTarget_(self)
        btn.setAction_(b'_clicked:')

    def _clicked_(self, sender):
        if is_recording:
            toggle_pause()
        else:
            if self._si:
                self._si.popUpStatusItemMenu_(self._si.menu())


_status_click_handler: "_StatusClickHandler | None" = None


class VoiceDropApp(rumps.App):

    _REC_FRAMES   = ["● REC", "  REC"]
    _SPIN_FRAMES  = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        super().__init__("VoiceDrop", title=None, quit_button=None)
        self._anim_on  = False
        self._anim_idx = 0

        self._start_item = rumps.MenuItem("Start Recording", callback=self._start_recording)
        self._stop_item = rumps.MenuItem("Stop & Transcribe", callback=self._stop_recording)
        self._pause_item = rumps.MenuItem("⏸  一時停止", callback=self._toggle_pause)
        self._hotkey_status_item = rumps.MenuItem("Hotkey: starting...", callback=None)

        self._hotkey_items = {}
        hotkey_sub = rumps.MenuItem("Hotkey")
        for label, key in HOTKEY_OPTIONS:
            item = rumps.MenuItem(label, callback=self._on_hotkey_select)
            hotkey_sub.update([item])
            self._hotkey_items[label] = (item, key)

        self._history_sub = rumps.MenuItem("📋  履歴")
        self._history_map: dict[str, str] = {}

        self.menu = [
            self._start_item,
            self._stop_item,
            self._pause_item,
            None,
            self._history_sub,
            None,
            self._hotkey_status_item,
            hotkey_sub,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]
        self._refresh_hotkey_menu()
        self._refresh_recording_menu()
        self._refresh_history_menu()
        self._set_waveform_icon()
        # 起動後に単クリックハンドラを設定（NSStatusItemが準備できてから）
        AppHelper.callLater(0.3, self._setup_click_handler)

    def _set_waveform_icon(self):
        if _WAVEFORM_PNG_PATH is None:
            self.title = "∿"
            return
        self._template = True           # フラグだけ先に立てる（reloadなし）
        self.icon = _WAVEFORM_PNG_PATH  # アイコンを先にセット
        self.title = None               # 最後にタイトルをクリア（fallbackOnNameが画像を見てOK）

    def _set_title(self, title):
        self.icon = None
        self.title = title

    def _refresh_history_menu(self):
        # clear existing items
        for key in list(self._history_sub.keys()):
            del self._history_sub[key]
        self._history_map = {}

        history = load_history()
        if not history:
            placeholder = rumps.MenuItem("（履歴なし）", callback=None)
            self._history_sub.update([placeholder])
            return

        for entry in history:
            preview = entry["text"].replace("\n", " ")
            label = f"{entry['ts']}  {preview[:42]}{'…' if len(preview) > 42 else ''}"
            # ensure unique key (rumps uses title as key)
            base, n = label, 1
            while label in self._history_map:
                label = f"{base} ({n})"
                n += 1
            self._history_map[label] = entry["text"]
            item = rumps.MenuItem(label, callback=self._on_history_select)
            self._history_sub.update([item])

    def _on_history_select(self, sender):
        text = self._history_map.get(sender.title)
        if text:
            _arm_click_to_paste(text)

    def refresh_history(self):
        """Call from background thread — dispatches to main thread."""
        AppHelper.callAfter(self._refresh_history_menu)

    def _refresh_hotkey_menu(self):
        current = config.get("hotkey", "f5")
        for label, (item, key) in self._hotkey_items.items():
            item.title = ("✓  " + label) if key == current else ("     " + label)

    def _on_hotkey_select(self, sender):
        label = sender.title.strip().lstrip("✓").strip()
        for lbl, key in HOTKEY_OPTIONS:
            if lbl.strip() == label:
                config["hotkey"] = key
                save_config()
                self._refresh_hotkey_menu()
                notify(
                    "VoiceDrop", "Hotkey changed",
                    f"New hotkey: {lbl.strip()}  (restart to apply)",
                )
                break

    def _quit(self, _):
        rumps.quit_application()

    def _start_recording(self, _):
        if not model_ready.is_set() or is_recording:
            return
        _trigger()

    def _stop_recording(self, _):
        if not is_recording:
            return
        _trigger()

    def _set_hotkey_status(self, text):
        self._hotkey_status_item.title = text

    @property
    def _status_item(self):
        return self._nsapp.nsstatusitem

    def _setup_click_handler(self):
        global _status_click_handler
        try:
            _status_click_handler = _StatusClickHandler.alloc().init()
            _status_click_handler.attach(self._status_item)
        except Exception:
            log_exception("_setup_click_handler failed")

    def _detach_menu(self):
        """録音中: メニューを外してボタンのactionを有効化"""
        try:
            self._status_item.setMenu_(None)
        except Exception:
            pass

    def _reattach_menu(self):
        """非録音中: メニューを再アタッチ"""
        try:
            self._status_item.setMenu_(self.menu._menu)
        except Exception:
            pass

    def _toggle_pause(self, _):
        toggle_pause()

    def _refresh_recording_menu(self):
        self._start_item.set_callback(self._start_recording)
        self._stop_item.set_callback(self._stop_recording)
        self._start_item.title = "Start Recording"
        self._stop_item.title = "Stop & Transcribe"
        self._start_item.state = 0
        self._stop_item.state = 0
        if is_recording:
            self._start_item.title = "Start Recording (busy)"
            self._pause_item.title = "▶  再開" if is_paused else "⏸  一時停止"
            self._pause_item.set_callback(self._toggle_pause)
        else:
            self._stop_item.title = "Stop & Transcribe (idle)"
            self._pause_item.title = "⏸  一時停止 (録音中のみ)"
            self._pause_item.set_callback(None)

    def show_recording(self):
        AppHelper.callAfter(self._show_recording)

    def show_paused(self):
        AppHelper.callAfter(self._show_paused)

    def _show_paused(self):
        self._anim_on = False
        self._set_title("⏸")
        self._refresh_recording_menu()
        self._detach_menu()

    def show_transcribing(self):
        AppHelper.callAfter(self._show_transcribing)

    def show_done(self):
        AppHelper.callAfter(self._show_done)

    def show_idle(self):
        AppHelper.callAfter(self._show_idle)

    def show_error(self, msg=""):
        AppHelper.callAfter(self._show_error, msg)

    def _show_recording(self):
        self._anim_on  = True
        self._anim_idx = 0
        self._refresh_recording_menu()
        self._detach_menu()
        self._animate_rec()

    def _show_transcribing(self):
        self._anim_on = False
        self._anim_idx = 0
        self._refresh_recording_menu()
        self._reattach_menu()
        self._animate_spin()

    def _show_done(self):
        self._anim_on = False
        self._set_title("✓")
        self._refresh_recording_menu()
        self._reattach_menu()
        AppHelper.callLater(2.0, self._show_idle)

    def _show_idle(self):
        self._anim_on = False
        self._set_waveform_icon()
        self._refresh_recording_menu()
        self._reattach_menu()

    def _show_error(self, msg=""):
        self._anim_on = False
        self._set_waveform_icon()
        self._refresh_recording_menu()
        self._reattach_menu()
        if msg:
            rumps.notification("VoiceDrop", "Error", msg, False)

    def _animate_rec(self):
        if not self._anim_on:
            return
        self._set_title(self._REC_FRAMES[self._anim_idx % 2])
        self._anim_idx += 1
        AppHelper.callLater(0.6, self._animate_rec)

    def _animate_spin(self):
        if self._anim_on:
            return
        # stop if another state already took over
        if self.title not in self._SPIN_FRAMES and self._anim_idx > 0:
            return
        self._set_title(self._SPIN_FRAMES[self._anim_idx % len(self._SPIN_FRAMES)])
        self._anim_idx += 1
        AppHelper.callLater(0.1, self._animate_spin)


# ══════════════════════════════════════════════════
#  Accessibility check
# ══════════════════════════════════════════════════
def check_accessibility():
    try:
        import ctypes, ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        if lib.AXIsProcessTrusted():
            if app:
                app._set_hotkey_status("Hotkey: ready")
            return True
        if app:
            app._set_hotkey_status("Hotkey: unavailable (use menu)")
        subprocess.run([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        ])
        notify(
            "VoiceDrop — 設定が必要",
            "アクセシビリティを許可してください",
            "システム設定 → プライバシー → アクセシビリティ → VoiceDrop を追加後、再起動",
        )
        return False
    except Exception:
        log_exception("check_accessibility failed")
        if app:
            app._set_hotkey_status("Hotkey: unavailable (use menu)")
        return False


# ══════════════════════════════════════════════════
#  Quartz helpers
# ══════════════════════════════════════════════════
def _save_mouse_pos():
    global saved_mouse_x, saved_mouse_y, saved_appkit_x, saved_appkit_y, saved_frontmost_app_name
    try:
        import Quartz as Q
        p = Q.CGEventGetLocation(Q.CGEventCreate(None))
        h = Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height
        saved_mouse_x, saved_mouse_y = p.x, p.y
        saved_appkit_x, saved_appkit_y = p.x, h - p.y
        app_ref = NSWorkspace.sharedWorkspace().frontmostApplication()
        saved_frontmost_app_name = app_ref.localizedName() if app_ref else ""
    except Exception:
        log_exception("failed to save mouse position")


def _record_click_target(x, y):
    global latest_click_x, latest_click_y, latest_click_app_name, click_target_ready
    try:
        import Quartz as Q
        latest_click_x, latest_click_y = x, y
        app_ref = NSWorkspace.sharedWorkspace().frontmostApplication()
        latest_click_app_name = app_ref.localizedName() if app_ref else ""
        click_target_ready = True
    except Exception:
        log_exception("failed to record click target")


def _click_on_overlay(x, y) -> bool:
    """クリック座標がRECオーバーレイの上なら True を返す（Quartz座標）"""
    if not is_recording or not overlay_ctrl or not overlay_ctrl._panel:
        return False
    try:
        import Quartz as Q
        h_screen = Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height
        ox1 = overlay_ctrl._px
        ox2 = overlay_ctrl._px + _OVERLAY_W
        oy1 = h_screen - (overlay_ctrl._py + _OVERLAY_H)
        oy2 = h_screen - overlay_ctrl._py
        hit = ox1 <= x <= ox2 and oy1 <= y <= oy2
        print(f"[OVERLAY] click=({x:.0f},{y:.0f}) overlay=({ox1:.0f}-{ox2:.0f}, {oy1:.0f}-{oy2:.0f}) hit={hit}", flush=True)
        return hit
    except Exception as e:
        print(f"[OVERLAY] error: {e}", flush=True)
        return False


def on_click(x, y, button, pressed):
    global pending_paste_armed
    if not pressed:
        return
    if synthetic_click_in_progress:
        return
    # RECオーバーレイをクリック → 一時停止 / 再開
    if _click_on_overlay(x, y):
        toggle_pause()
        return
    if pending_paste_armed and not is_recording:
        _record_click_target(x, y)
        pending_paste_armed = False
        threading.Thread(target=_paste_after_user_click, daemon=True).start()
        return
    if not is_recording:
        return
    _record_click_target(x, y)

def _click_at_saved_pos():
    try:
        import Quartz as Q
        pos = Q.CGPointMake(saved_mouse_x, saved_mouse_y)
        for et in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            ev = Q.CGEventCreateMouseEvent(None, et, pos, Q.kCGMouseButtonLeft)
            Q.CGEventSetFlags(ev, 0)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
    except Exception:
        pass


def _click_at_latest_target():
    if not click_target_ready:
        return False
    try:
        import Quartz as Q
        global synthetic_click_in_progress
        synthetic_click_in_progress = True
        pos = Q.CGPointMake(latest_click_x, latest_click_y)
        for et in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            ev = Q.CGEventCreateMouseEvent(None, et, pos, Q.kCGMouseButtonLeft)
            Q.CGEventSetFlags(ev, 0)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
        synthetic_click_in_progress = False
        return True
    except Exception:
        synthetic_click_in_progress = False
        log_exception("failed to click latest target")
        return False

def _send_cmd_v():
    try:
        import Quartz as Q
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, 9, down)
            Q.CGEventSetFlags(ev, Q.kCGEventFlagMaskCommand)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
        return True
    except Exception:
        return False


def _restore_target_app_focus():
    app_name = latest_click_app_name if click_target_ready and latest_click_app_name else saved_frontmost_app_name
    if not app_name:
        return False
    try:
        script = f'tell application "{app_name.replace(chr(34), chr(92) + chr(34))}" to activate'
        subprocess.run(["osascript", "-e", script], check=True)
        time.sleep(0.2)
        return True
    except Exception:
        return False


def _paste_at_saved_pos():
    _restore_target_app_focus()
    if not _click_at_latest_target():
        _click_at_saved_pos()
    time.sleep(0.2)
    ok = _send_cmd_v()
    return ok


def _arm_click_to_paste(text):
    global pending_paste_armed
    pending_paste_armed = True
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    notify(
        "VoiceDrop",
        "貼り付け待機中",
        "貼り付けたい入力欄を1回クリックすると自動で貼り付けます",
    )


def _paste_after_user_click():
    time.sleep(0.15)
    try:
        if latest_click_app_name:
            script = f'tell application "{latest_click_app_name.replace(chr(34), chr(92) + chr(34))}" to activate'
            subprocess.run(["osascript", "-e", script], check=True)
            time.sleep(0.15)
        ok = _send_cmd_v()
        if app:
            app.show_done()
        if not ok:
            notify(
                "VoiceDrop",
                "貼り付けに失敗",
                "クリック先には自動貼り付けできませんでした。Cmd+V を試してください",
            )
    except Exception:
        log_exception("deferred paste failed")
        if app:
            app.show_error("クリック後の貼り付けに失敗しました")


def _cancel_recording_timer():
    global recording_timer
    if recording_timer:
        recording_timer.cancel()
        recording_timer = None


def _schedule_auto_stop():
    global recording_timer
    _cancel_recording_timer()
    recording_timer = threading.Timer(MAX_RECORDING_SECONDS, _auto_stop_recording)
    recording_timer.daemon = True
    recording_timer.start()


def _auto_stop_recording():
    if not is_recording:
        return
    notify(
        "VoiceDrop",
        "5分で自動停止しました",
        "文字起こしを開始します",
    )
    stop_and_transcribe(auto_stopped=True)


def pause_recording():
    global is_paused
    if not is_recording or is_paused:
        return
    is_paused = True
    if app:
        app.show_paused()
    if overlay_ctrl:
        overlay_ctrl.refresh()

def resume_recording():
    global is_paused
    if not is_recording or not is_paused:
        return
    is_paused = False
    if app:
        app.show_recording()
    if overlay_ctrl:
        overlay_ctrl.refresh()

def toggle_pause():
    if is_paused:
        threading.Thread(target=resume_recording, daemon=True).start()
    else:
        threading.Thread(target=pause_recording, daemon=True).start()


def _transcript_path():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return TRANSCRIPT_DIR / f"VoiceDrop_{stamp}.txt"


def _save_transcript_to_file(text):
    path = _transcript_path()
    path.write_text(text, encoding="utf-8")
    return path


# Whisper が無音・認識不能時に出力する定番ハルシネーション
_HALLUCINATION_PHRASES = {
    "ご視聴ありがとうございました",
    "ありがとうございました",
    "チャンネル登録よろしくお願いします",
    "チャンネル登録お願いします",
    "字幕は自動生成されています",
    "Thank you for watching.",
    "Thanks for watching.",
    "Please subscribe.",
    "MBC 뉴스 이덕영입니다",
}

def _is_hallucination(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    # 句読点・空白を除いて比較（「ご視聴ありがとうございました。」も除去）
    t_norm = _re.sub(r'[。、.,!?！？\s]', '', t)
    for phrase in _HALLUCINATION_PHRASES:
        p_norm = _re.sub(r'[。、.,!?！？\s]', '', phrase)
        if t_norm == p_norm:
            return True
    return False


def _dedup_repeats(text: str) -> str:
    """ご視聴… / コ連打 / 指連打などの繰り返しを除去する"""
    # 同じ文字が3回以上連続 → 1回に (コここここ → コ)
    text = _re.sub(r'(.)\1{2,}', r'\1', text)
    # 同じ単語/フレーズが3回以上 → 1回に (指を指を指を → 指を)
    text = _re.sub(r'(\S{1,10})\1{2,}', r'\1', text)
    return text.strip()


def _transcribe_audio_chunks(audio):
    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=MLX_MODEL_REPO,
        language=LANGUAGE,
        initial_prompt="以下は日本語の音声です。句読点（。、）を適切に含めて文字起こししてください。",
        condition_on_previous_text=False,  # ループハルシネーション防止
        temperature=0.0,                   # 貪欲デコード（最速）
    )
    text = _dedup_repeats(result.get("text", "").strip())
    if _is_hallucination(text):
        return ""
    return text


# ══════════════════════════════════════════════════
#  Recording
# ══════════════════════════════════════════════════
app: VoiceDropApp = None

def audio_callback(indata, frames, time_info, status):
    global audio_level
    if is_recording and not is_paused:
        audio_buffer.extend(indata[:, 0].tolist())
        audio_level = float(np.sqrt(np.mean(indata ** 2))) * 3.5
    elif is_paused:
        audio_level = 0.0

def start_recording():
    global is_recording, is_paused, audio_buffer, stream, recording_started_at, click_target_ready, pending_paste_armed
    try:
        audio_buffer = []
        is_recording = True
        is_paused    = False  # 前回の状態が残らないよう必ずリセット
        click_target_ready = False
        pending_paste_armed = False
        recording_started_at = time.monotonic()
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", callback=audio_callback)
        stream.start()
        _schedule_auto_stop()
        if app:
            app.show_recording()
        if overlay_ctrl:
            overlay_ctrl.show_near(saved_appkit_x, saved_appkit_y)
    except Exception:
        is_recording = False
        if stream:
            stream.stop(); stream.close(); stream = None
        log_exception("start_recording failed")
        if app:
            app.show_error("録音を開始できませんでした")

def stop_and_transcribe(auto_stopped=False):
    global is_recording, is_transcribing, stream, audio_level, is_paused
    with stop_lock:
        if not is_recording and stream is None:
            return

        is_recording = False
        is_paused    = False
        is_transcribing = True
        audio_level  = 0.0
        _cancel_recording_timer()
        _save_mouse_pos()
        if stream:
            stream.stop(); stream.close(); stream = None

        # Hide overlay immediately when recording stops
        if overlay_ctrl:
            overlay_ctrl.hide()

        audio = np.array(audio_buffer, dtype=np.float32)

    if len(audio) < SAMPLE_RATE * 0.3:
        is_transcribing = False
        if app:
            app.show_idle()
        return

    if app:
        app.show_transcribing()

    def _run():
        global is_transcribing
        try:
            text = _transcribe_audio_chunks(audio)
            if not text:
                if app:
                    app.show_idle()
                return

            save_to_history(text)
            if app:
                app.refresh_history()

            should_save_to_file = len(audio) >= SAMPLE_RATE * FILE_SAVE_MINUTES_THRESHOLD

            if should_save_to_file:
                path = _save_transcript_to_file(text)
                if app:
                    app.show_done()
                notify(
                    "VoiceDrop",
                    "長文のためファイル保存しました",
                    str(path),
                )
                return

            _arm_click_to_paste(text)
            if app:
                app.show_idle()
            if auto_stopped:
                notify(
                    "VoiceDrop",
                    "自動停止しました",
                    "次にクリックした場所へ貼り付け待機中です",
                )
        except Exception:
            log_exception("transcription flow failed")
            if app:
                app.show_error("文字起こしまたは出力に失敗しました")
        finally:
            is_transcribing = False

    threading.Thread(target=_run, daemon=True).start()


# ══════════════════════════════════════════════════
#  CGEventTap: Right Option を OS レベルで横取り
#  (Claudeのdouble-tap-option検出より前に処理)
# ══════════════════════════════════════════════════
def _on_right_option_down():
    global hotkey_active, _press_start_time, _press_was_start
    if hotkey_active:
        return
    hotkey_active = True
    _press_start_time = time.time()
    if not is_recording and not is_transcribing and model_ready.is_set():
        _press_was_start = True
        threading.Thread(target=start_recording, daemon=True).start()
    else:
        _press_was_start = False


def _on_right_option_up():
    global hotkey_active, _press_was_start, _last_pause_press
    hotkey_active = False
    if _press_was_start:
        _press_was_start = False
        return
    if is_recording:
        now = time.time()
        elapsed = now - _last_pause_press
        if elapsed < _DOUBLE_PRESS_SEC:
            threading.Thread(target=stop_and_transcribe, daemon=True).start()
        else:
            _last_pause_press = now
            toggle_pause()




def _setup_event_tap():
    """メインスレッドから呼ぶ（AppHelper.callLater経由）"""
    global _active_event_tap, _tap_cb_ref
    try:
        # ctypesでcallbackを正しくwrap（PyObjCの型変換問題を回避）
        _TAP_CB = ctypes.CFUNCTYPE(
            ctypes.c_void_p,   # CGEventRef return (NULL=discard)
            ctypes.c_void_p,   # CGEventTapProxy
            ctypes.c_uint32,   # CGEventType
            ctypes.c_void_p,   # CGEventRef
            ctypes.c_void_p,   # userInfo
        )

        # ctypesで直接CoreGraphicsを呼ぶ（PyObjC変換コストを避けてcallbackを高速化）
        _CG = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        _CG.CGEventGetIntegerValueField.restype = ctypes.c_int64
        _CG.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _kDown = 10        # kCGEventKeyDown
        _kUp   = 11        # kCGEventKeyUp
        _kTO   = 0xFFFFFFFE  # kCGEventTapDisabledByTimeout
        _kKeycode = 9      # kCGKeyboardEventKeycode

        def _raw_callback(proxy, event_type, event, refcon):
            try:
                if event_type == _kTO:
                    if _active_event_tap:
                        _Q.CGEventTapEnable(_active_event_tap, True)
                    return event

                if event_type == _kDown or event_type == _kUp:
                    vk = _CG.CGEventGetIntegerValueField(event, _kKeycode)
                    if vk == _RIGHT_OPTION_VK:
                        if event_type == _kDown:
                            threading.Thread(target=_on_right_option_down, daemon=True).start()
                        else:
                            threading.Thread(target=_on_right_option_up, daemon=True).start()
                        return None  # イベント破棄
            except Exception as e:
                print(f"[TAP] error: {e}", flush=True)
            return event

        _tap_cb_ref = _TAP_CB(_raw_callback)  # GC防止のためグローバルに保持

        mask = (1 << int(_Q.kCGEventKeyDown)) | (1 << int(_Q.kCGEventKeyUp))

        for tap_level in (_Q.kCGHIDEventTap, _Q.kCGSessionEventTap):
            tap = _Q.CGEventTapCreate(
                tap_level,
                _Q.kCGHeadInsertEventTap,
                _Q.kCGEventTapOptionDefault,
                mask,
                _tap_cb_ref,
                None,
            )
            if tap:
                src = _Q.CFMachPortCreateRunLoopSource(None, tap, 0)
                from Foundation import NSRunLoopCommonModes
                _Q.CFRunLoopAddSource(_Q.CFRunLoopGetMain(), src, NSRunLoopCommonModes)
                _Q.CGEventTapEnable(tap, True)
                _active_event_tap = tap
                print(f"[TAP] CGEventTap level={tap_level} 作成成功", flush=True)
                break
            else:
                print(f"[TAP] level={tap_level} 失敗", flush=True)
        else:
            print("[TAP] CGEventTap作成失敗 (アクセシビリティ権限確認してください)", flush=True)
    except Exception:
        log_exception("_setup_event_tap failed")


# ══════════════════════════════════════════════════
#  Hotkey listener
# ══════════════════════════════════════════════════
def _trigger():
    if not model_ready.is_set():
        return
    if is_transcribing:
        notify(
            "VoiceDrop",
            "文字起こし中です",
            "完了してから次の録音を開始してください",
        )
        return
    if not is_recording:
        threading.Thread(target=start_recording,     daemon=True).start()
    else:
        threading.Thread(target=stop_and_transcribe, daemon=True).start()



def _alt_held():
    return any(k in current_keys for k in
               (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r))


def _right_alt_pressed(key):
    return key == keyboard.Key.alt_r

def on_press(key):
    global hotkey_active, _press_start_time, _press_was_start
    current_keys.add(key)

    hk = config.get("hotkey", "right_cmd")

    if hk == "right_option":
        if key == keyboard.Key.alt_r and not hotkey_active:
            threading.Thread(target=_on_right_option_down, daemon=True).start()
    elif hk == "right_cmd":
        if key == keyboard.Key.cmd_r and not hotkey_active:
            hotkey_active = True
            _trigger()
    elif hk == "opt_space":
        is_space = (key == keyboard.Key.space or
                    (hasattr(key, 'vk') and key.vk == 49) or
                    (hasattr(key, 'char') and key.char in (' ', '\xa0')))
        if is_space and _alt_held() and not hotkey_active:
            hotkey_active = True
            _trigger()
    elif hk == "ctrl_shift_space":
        ctrl  = any(k in current_keys for k in
                    (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r))
        shift = any(k in current_keys for k in
                    (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r))
        space = keyboard.Key.space in current_keys
        if ctrl and shift and space and not hotkey_active:
            hotkey_active = True
            _trigger()
    elif hk == "mic_key":
        if key == keyboard.KeyCode(vk=MIC_VK) and not hotkey_active:
            hotkey_active = True
            _trigger()
    else:
        target = getattr(keyboard.Key, hk, keyboard.Key.f5)
        if key == target and not hotkey_active:
            hotkey_active = True
            _trigger()

def on_release(key):
    global hotkey_active, _press_was_start
    current_keys.discard(key)
    hk = config.get("hotkey", "right_cmd")
    if hk == "right_option":
        if key == keyboard.Key.alt_r:
            threading.Thread(target=_on_right_option_up, daemon=True).start()
    elif hk == "right_cmd":
        if key == keyboard.Key.cmd_r:
            hotkey_active = False
    elif hk == "opt_space":
        if key in (keyboard.Key.space, keyboard.Key.alt,
                   keyboard.Key.alt_l, keyboard.Key.alt_r):
            if not (keyboard.Key.space in current_keys and _alt_held()):
                hotkey_active = False
    elif hk == "ctrl_shift_space":
        ctrl  = any(k in current_keys for k in
                    (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r))
        shift = any(k in current_keys for k in
                    (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r))
        space = keyboard.Key.space in current_keys
        if not (ctrl and shift and space):
            hotkey_active = False
    elif hk == "mic_key":
        if key == keyboard.KeyCode(vk=MIC_VK):
            hotkey_active = False
    else:
        target = getattr(keyboard.Key, hk, keyboard.Key.f5)
        if key == target:
            hotkey_active = False


# ══════════════════════════════════════════════════
#  Boot
# ══════════════════════════════════════════════════
def load_model():
    try:
        # モデルをダウンロード＆キャッシュ、Neural Engine をウォームアップ
        silent = np.zeros(SAMPLE_RATE, dtype=np.float32)
        mlx_whisper.transcribe(silent, path_or_hf_repo=MLX_MODEL_REPO, language=LANGUAGE)
        model_ready.set()
    except Exception:
        log_exception("model load failed")
        if app:
            app.show_error("Whisper モデルの読込に失敗しました")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    load_config()
    if not acquire_single_instance_lock():
        sys.exit(0)
    try:
        _WAVEFORM_PNG_PATH = _build_waveform_png()
    except Exception:
        pass
    app = VoiceDropApp()
    overlay_ctrl = MicOverlay.alloc().init()

    threading.Thread(target=check_accessibility, daemon=True).start()
    threading.Thread(target=load_model, daemon=False).start()

    def _listener():
        with keyboard.Listener(on_press=on_press, on_release=on_release) as lst:
            lst.join()
    threading.Thread(target=_listener, daemon=True).start()

    def _mouse_listener():
        with mouse.Listener(on_click=on_click) as lst:
            lst.join()
    threading.Thread(target=_mouse_listener, daemon=True).start()

    app.run()
