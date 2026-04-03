#!/usr/bin/env python3

from __future__ import annotations

import argparse
import atexit
import itertools
import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import rumps
import sounddevice as sd
from AppKit import NSPasteboard, NSPasteboardTypeString
from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
from PyObjCTools import AppHelper
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CFRunLoopStop,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventSourceKeyState,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagsChanged,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCGEventSourceStateCombinedSessionState,
)
from scipy.io.wavfile import write as write_wav


APP_NAME = "VoiceDrop"
APP_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / "Library/Application Support/VoiceDrop"
LOG_DIR = Path.home() / "Library/Logs/VoiceDrop"
TRANSCRIPTS_DIR = Path.home() / "Desktop/VoiceDrop Transcripts"
ARCHIVED_AUDIO_DIR = TRANSCRIPTS_DIR / "Audio"
IN_PROGRESS_AUDIO_DIR = ARCHIVED_AUDIO_DIR / "InProgress"
TERM_GLOSSARY_FILE = APP_DIR / "transcription_terms.json"
PID_FILE = STATE_DIR / "voicedrop.pid"
LAST_TRANSCRIPT_FILE = STATE_DIR / "last_transcript.txt"
LAST_AUDIO_FILE = STATE_DIR / "last_recording.wav"
LOG_FILE = LOG_DIR / "voicedrop.log"
MODEL_PREF_FILE = STATE_DIR / "model_preference.txt"
MODEL_OPTIONS = [
    ("mlx-community/whisper-small-mlx", "Small (~300MB, faster)"),
    ("mlx-community/whisper-large-v3-turbo", "Large v3 Turbo (~1.5GB, best accuracy)"),
]
SAMPLE_RATE = 16_000
MIN_RECORDING_SECONDS = 0.35
RIGHT_OPTION_KEYCODE = 61
SPINNER_FRAMES = ("TX|", "TX/", "TX-", "TX\\")
RECORDING_SEGMENT_SECONDS = 1.0
AUDIO_ARCHIVE_BITRATE = os.getenv("VOICEDROP_AUDIO_BITRATE", "192k")
STOP_OPERATION_TIMEOUT_SECONDS = float(
    os.getenv("VOICEDROP_STOP_TIMEOUT_SECONDS", "5.0")
)
MAX_RECORDING_SECONDS = float(
    os.getenv("VOICEDROP_MAX_RECORDING_SECONDS", "3600")
)
LIVE_COMMA_GAP_SECONDS = float(
    os.getenv("VOICEDROP_LIVE_COMMA_GAP_SECONDS", "0.55")
)
LIVE_SENTENCE_GAP_SECONDS = float(
    os.getenv("VOICEDROP_LIVE_SENTENCE_GAP_SECONDS", "1.15")
)
LIVE_PARAGRAPH_GAP_SECONDS = float(
    os.getenv("VOICEDROP_LIVE_PARAGRAPH_GAP_SECONDS", "4.5")
)
LIVE_COMMA_MIN_CHARS = int(
    os.getenv("VOICEDROP_LIVE_COMMA_MIN_CHARS", "6")
)
SILENCE_RMS_THRESHOLD = 0.0035
SILENCE_PEAK_THRESHOLD = 0.02
SILENCE_ACTIVE_RATIO_THRESHOLD = 0.008
JAPANESE_TRANSCRIPTION_PROMPT = (
    "以下は自然な日本語の音声文字起こしです。"
    "句読点は「、」「。」を中心に自然に補い、文末は必要に応じて「。」で閉じてください。"
    "話題転換や長い間があるところでは自然な改行も入れてください。"
    "余計な半角スペースは入れず、そのまま自然な日本語として出力してください。"
)
ENGLISH_TRANSCRIPTION_PROMPT = (
    "Transcribe in natural English."
    " Add punctuation and capitalization."
    " Close complete sentences with periods, and add paragraph breaks when the speaker pauses or changes topic."
)
MULTILINGUAL_TRANSCRIPTION_PROMPT = (
    "Transcribe in the language that is actually spoken."
    " Add natural punctuation and paragraph breaks."
    " For Japanese, use 「、」「。」."
    " For English and other Latin-script languages, use normal punctuation such as commas and periods."
)
DEFAULT_TERM_GLOSSARY = {
    "ボイスドロップ": "VoiceDrop",
    "ボイス ドロップ": "VoiceDrop",
    "ヴォイスドロップ": "VoiceDrop",
    "ヴォイス ドロップ": "VoiceDrop",
    "ボイス・ドロップ": "VoiceDrop",
    "右オプションキー": "Right Option",
    "ライトオプション": "Right Option",
    "ライトオプションキー": "Right Option",
    "ライト オプション": "Right Option",
    "右オプション": "Right Option",
    "オプションキー": "Option key",
}
CANONICAL_ENGLISH_REPLACEMENTS = (
    (r"\bvoice\s+drop\b", "VoiceDrop"),
    (r"右\s*Option key", "Right Option"),
    (r"右\s*option key", "Right Option"),
    (r"右\s*option", "Right Option"),
    (r"\bright\s+option\b", "Right Option"),
    (r"\boption\s+key\b", "Option key"),
)
JAPANESE_CHAR_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff々ー]")
LATIN_CHAR_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
HALLUCINATION_FILTER_PHRASES = {
    "ご視聴ありがとうございます",
    "ご視聴ありがとうございました",
}
LOGGER = logging.getLogger(APP_NAME)


def ensure_runtime_path() -> None:
    current_parts = [part for part in os.environ.get("PATH", "").split(":") if part]
    desired_prefixes = ["/opt/homebrew/bin", "/usr/local/bin"]
    path_parts = desired_prefixes + [part for part in current_parts if part not in desired_prefixes]
    os.environ["PATH"] = ":".join(path_parts)


ensure_runtime_path()


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVED_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    IN_PROGRESS_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    ensure_dirs()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s %(message)s"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)


def write_pid_file() -> None:
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def remove_pid_file() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(
            os.getpid()
        ):
            PID_FILE.unlink()
    except Exception:
        LOGGER.exception("Failed to remove PID file")


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def open_in_finder(path: Path) -> None:
    subprocess.Popen(["open", str(path)])


def send_notification(title: str, message: str) -> None:
    try:
        rumps.notification(APP_NAME, title, message)
    except Exception:
        LOGGER.exception("Notification failed: %s - %s", title, message)


def copy_to_clipboard(text: str) -> None:
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)


def paste_into_focused_app() -> None:
    script = 'tell application "System Events" to keystroke "v" using command down'
    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )


def utc_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


class NoSpeechDetectedError(RuntimeError):
    pass


def float_audio_to_pcm16(audio: np.ndarray) -> np.ndarray:
    clipped = np.clip(audio, -1.0, 1.0)
    return np.round(clipped * 32767.0).astype(np.int16)


def analyze_audio_levels(audio: np.ndarray) -> tuple[float, float, float]:
    if audio.size == 0:
        return 0.0, 0.0, 0.0

    abs_audio = np.abs(audio.astype(np.float64, copy=False))
    peak = float(abs_audio.max(initial=0.0))
    rms = float(np.sqrt(np.mean(np.square(abs_audio), dtype=np.float64)))
    active_ratio = float(np.mean(abs_audio >= SILENCE_PEAK_THRESHOLD))
    return peak, rms, active_ratio


def is_effectively_silent(audio: np.ndarray) -> bool:
    peak, rms, active_ratio = analyze_audio_levels(audio)
    LOGGER.info(
        "Audio levels peak=%.4f rms=%.4f active_ratio=%.4f",
        peak,
        rms,
        active_ratio,
    )
    return (
        peak < SILENCE_PEAK_THRESHOLD
        and rms < SILENCE_RMS_THRESHOLD
        and active_ratio < SILENCE_ACTIVE_RATIO_THRESHOLD
    )


def is_effectively_silent_metrics(peak: float, rms: float, active_ratio: float) -> bool:
    LOGGER.info(
        "Audio stats peak=%.4f rms=%.4f active_ratio=%.4f",
        peak,
        rms,
        active_ratio,
    )
    return (
        peak < SILENCE_PEAK_THRESHOLD
        and rms < SILENCE_RMS_THRESHOLD
        and active_ratio < SILENCE_ACTIVE_RATIO_THRESHOLD
    )


def load_term_glossary() -> dict[str, str]:
    glossary = dict(DEFAULT_TERM_GLOSSARY)

    if not TERM_GLOSSARY_FILE.exists():
        return glossary

    try:
        loaded = json.loads(TERM_GLOSSARY_FILE.read_text(encoding="utf-8"))
    except Exception:
        LOGGER.exception("Failed to read term glossary: %s", TERM_GLOSSARY_FILE)
        return glossary

    if not isinstance(loaded, dict):
        LOGGER.warning("Ignoring invalid term glossary format: %s", TERM_GLOSSARY_FILE)
        return glossary

    for source, target in loaded.items():
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        source = source.strip()
        target = target.strip()
        if source and target:
            glossary[source] = target

    return glossary


def build_initial_prompt(language: str | None, glossary: dict[str, str]) -> str:
    prompt_parts: list[str] = []
    if language == "ja":
        prompt_parts.append(JAPANESE_TRANSCRIPTION_PROMPT)
    elif language == "en":
        prompt_parts.append(ENGLISH_TRANSCRIPTION_PROMPT)
    else:
        prompt_parts.append(MULTILINGUAL_TRANSCRIPTION_PROMPT)

    if glossary:
        examples = "、".join(
            f"{source}->{target}"
            for source, target in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True)[:8]
        )
        prompt_parts.append(
            "固有名詞やカタカナ語は、既知のものは英字表記を優先してください。"
            f"例: {examples}"
        )

    return " ".join(part for part in prompt_parts if part).strip()


def apply_term_glossary(text: str, glossary: dict[str, str]) -> str:
    normalized = text

    for source, target in sorted(glossary.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(source, target)

    for pattern, replacement in CANONICAL_ENGLISH_REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

    return normalized


def normalize_transcript_text(
    text: str,
    language: str,
    glossary: dict[str, str] | None = None,
    *,
    add_terminal_punctuation: bool = True,
) -> str:
    text = text.strip()
    if not text:
        return text

    text = re.sub(r"[ \t]+", " ", text)

    is_japanese = language == "ja" or bool(JAPANESE_CHAR_PATTERN.search(text))
    is_latin = language == "en" or bool(LATIN_CHAR_PATTERN.search(text))

    if not is_japanese:
        text = text.replace("，", ",")
        text = text.replace("､", ",")
        text = text.replace("｡", ".")
        text = text.replace("．", ".")
        text = text.replace("！", "!")
        text = text.replace("？", "?")
        text = re.sub(r"[ \t]*([,.;:!?])[ \t]*", r"\1 ", text)
        text = re.sub(r"([,.;:!?]){2,}", r"\1", text)
        text = re.sub(r" +\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        if glossary:
            text = apply_term_glossary(text, glossary)
        if add_terminal_punctuation and is_latin and text and not re.search(r"[.!?]$", text):
            text += "."
        return text

    text = text.replace("，", "、")
    text = text.replace("､", "、")
    text = text.replace(",", "、")
    text = text.replace("｡", "。")
    text = text.replace("．", "。")
    text = text.replace("!", "！")
    text = text.replace("?", "？")
    text = text.replace(":", "：")
    text = text.replace(";", "；")
    text = re.sub(r"(?<!\d)\.(?!\d)", "。", text)

    text = re.sub(r"[ \t]*([、。！？：；])[ \t]*", r"\1", text)
    text = re.sub(
        r"(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff々ー])\s+(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff々ー])",
        "",
        text,
    )
    text = re.sub(r"([、。！？]){2,}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if (
        add_terminal_punctuation
        and JAPANESE_CHAR_PATTERN.search(text)
        and not re.search(r"[。！？]$", text)
    ):
        text += "。"

    if glossary:
        text = apply_term_glossary(text, glossary)

    return text


def is_filtered_hallucination(text: str) -> bool:
    collapsed = re.sub(r"[、。！？\s]+", "", text)
    if not collapsed:
        return True
    if collapsed in HALLUCINATION_FILTER_PHRASES:
        return True
    # Whisper repetition hallucination: short pattern repeated many times
    for length in range(1, 8):
        if len(collapsed) >= length * 6:
            pattern = collapsed[:length]
            repetitions = len(collapsed) // length
            if collapsed == pattern * repetitions:
                return True
    return False


@dataclass
class RecordingResult:
    duration_seconds: float
    started_stamp: str
    session_dir: Path
    segment_paths: list[Path]
    peak: float
    rms: float
    active_ratio: float


@dataclass(order=True)
class TranscriptionJob:
    priority: int
    sequence: int
    kind: str = field(compare=False)
    audio_path: Path = field(compare=False)
    stamp: str = field(compare=False)
    source_path: Path | None = field(compare=False, default=None)
    archive_path: Path | None = field(compare=False, default=None)
    output_inbox: Path | None = field(compare=False, default=None)


class RollingAudioWriter:
    def __init__(self, started_stamp: str) -> None:
        self.started_stamp = started_stamp
        self.session_dir = IN_PROGRESS_AUDIO_DIR / f"VoiceDrop_{started_stamp}.inprogress"
        self.segments_dir = self.session_dir / "segments"
        self.manifest_path = self.session_dir / "recording.json"
        self.segment_frames = int(SAMPLE_RATE * RECORDING_SEGMENT_SECONDS)
        self.segment_paths: list[Path] = []
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="audio-writer",
            daemon=True,
        )
        self._buffer = np.empty(0, dtype=np.float32)
        self._segment_index = 0

    def start(self) -> None:
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        self._write_manifest("recording")
        self._thread.start()

    def append_chunk(self, audio: np.ndarray) -> None:
        self._queue.put(audio.astype(np.float32, copy=True))

    def stop(self) -> list[Path]:
        self._queue.put(None)
        self._thread.join()
        self._write_manifest(
            "stopped",
            {
                "segment_count": len(self.segment_paths),
                "segments": [path.name for path in self.segment_paths],
            },
        )
        return list(self.segment_paths)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._buffer = np.concatenate((self._buffer, item))
            while self._buffer.size >= self.segment_frames:
                self._write_segment(self._buffer[: self.segment_frames])
                self._buffer = self._buffer[self.segment_frames :]

        if self._buffer.size:
            self._write_segment(self._buffer)
            self._buffer = np.empty(0, dtype=np.float32)

    def _write_segment(self, audio: np.ndarray) -> None:
        segment_path = self.segments_dir / f"{self._segment_index:06d}.wav"
        write_wav(segment_path, SAMPLE_RATE, float_audio_to_pcm16(audio))
        self.segment_paths.append(segment_path)
        self._segment_index += 1

    def _write_manifest(self, status: str, extra: dict[str, object] | None = None) -> None:
        payload: dict[str, object] = {
            "status": status,
            "started_stamp": self.started_stamp,
            "sample_rate": SAMPLE_RATE,
            "segment_seconds": RECORDING_SEGMENT_SECONDS,
        }
        if extra:
            payload.update(extra)
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def merge_wav_segments(segment_paths: list[Path], output_path: Path) -> None:
    if not segment_paths:
        raise RuntimeError("No audio segments were captured.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out_file:
        out_file.setnchannels(1)
        out_file.setsampwidth(2)
        out_file.setframerate(SAMPLE_RATE)

        for segment_path in segment_paths:
            with wave.open(str(segment_path), "rb") as in_file:
                out_file.writeframes(in_file.readframes(in_file.getnframes()))


def encode_mp3_archive(input_wav: Path, output_mp3: Path) -> None:
    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_wav),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            AUDIO_ARCHIVE_BITRATE,
            str(output_mp3),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def sanitize_filename_component(text: str, fallback: str = "item", max_length: int = 40) -> str:
    normalized = re.sub(r"\s+", "_", text.strip())
    normalized = re.sub(r"[^\w\-]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = fallback
    return normalized[:max_length]


def build_transcript_label(text: str, fallback: str = "speech") -> str:
    sentence = re.split(r"[\n。！？.!?]", text, maxsplit=1)[0].strip()
    return sanitize_filename_component(sentence, fallback=fallback, max_length=32)


def make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def make_unique_dir(path: Path) -> Path:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=False)
        return path

    counter = 2
    while True:
        candidate = path.with_name(f"{path.name}_{counter}")
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        counter += 1


class AudioRecorder:
    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._started_stamp: str | None = None
        self._writer: RollingAudioWriter | None = None
        self._peak = 0.0
        self._sum_squares = 0.0
        self._active_samples = 0
        self._total_samples = 0

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    @property
    def recording_stamp(self) -> str | None:
        return self._started_stamp

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            LOGGER.warning("Audio callback status: %s", status)
        audio = indata.reshape(-1).astype(np.float32, copy=True)
        abs_audio = np.abs(audio, dtype=np.float32)
        peak = float(abs_audio.max(initial=0.0))
        sum_squares = float(np.square(audio, dtype=np.float32).sum(dtype=np.float64))
        active_samples = int(np.count_nonzero(abs_audio >= SILENCE_PEAK_THRESHOLD))

        with self._lock:
            self._peak = max(self._peak, peak)
            self._sum_squares += sum_squares
            self._active_samples += active_samples
            self._total_samples += int(audio.size)
            writer = self._writer

        if writer is not None:
            writer.append_chunk(audio)

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("Recording already in progress")
        self._started_stamp = utc_timestamp()
        self._writer = RollingAudioWriter(self._started_stamp)
        self._writer.start()
        self._peak = 0.0
        self._sum_squares = 0.0
        self._active_samples = 0
        self._total_samples = 0
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._callback,
            blocksize=0,
        )
        self._stream.start()
        self._started_at = time.time()
        LOGGER.info("Recording started")

    def stop(self) -> RecordingResult:
        if (
            self._stream is None
            or self._started_at is None
            or self._started_stamp is None
            or self._writer is None
        ):
            raise RuntimeError("Recording is not active")

        stream = self._stream
        self._stream = None
        writer = self._writer
        self._writer = None
        # stream.stop() can deadlock in PortAudio when called shortly after start.
        # Run it in a daemon thread with a timeout so the stop never hangs forever.
        _stop_thread = threading.Thread(target=stream.stop, daemon=True)
        _stop_thread.start()
        _stop_thread.join(timeout=3.0)
        try:
            stream.close()
        except Exception:
            pass

        duration_seconds = time.time() - self._started_at
        self._started_at = None
        started_stamp = self._started_stamp
        self._started_stamp = None
        segment_paths = writer.stop()

        with self._lock:
            peak = self._peak
            total_samples = self._total_samples
            active_samples = self._active_samples
            sum_squares = self._sum_squares
            self._peak = 0.0
            self._sum_squares = 0.0
            self._active_samples = 0
            self._total_samples = 0

        rms = float(np.sqrt(sum_squares / total_samples)) if total_samples else 0.0
        active_ratio = float(active_samples / total_samples) if total_samples else 0.0

        LOGGER.info("Recording stopped after %.2f seconds", duration_seconds)
        return RecordingResult(
            duration_seconds=duration_seconds,
            started_stamp=started_stamp,
            session_dir=writer.session_dir,
            segment_paths=segment_paths,
            peak=peak,
            rms=rms,
            active_ratio=active_ratio,
        )


class Transcriber:
    def __init__(self) -> None:
        self._faster_model = None
        self._faster_lock = threading.Lock()
        self._warmup_started = False

        self.faster_model_name = os.getenv("VOICEDROP_MODEL", "small")
        self.faster_compute_type = os.getenv("VOICEDROP_COMPUTE_TYPE", "int8")
        self.language = os.getenv("VOICEDROP_LANGUAGE") or None
        self.term_glossary = load_term_glossary()
        default_prompt = build_initial_prompt(self.language, self.term_glossary)
        self.initial_prompt = os.getenv("VOICEDROP_INITIAL_PROMPT", default_prompt).strip()
        _saved_model = MODEL_PREF_FILE.read_text().strip() if MODEL_PREF_FILE.exists() else None
        self.mlx_model_name = _saved_model or os.getenv(
            "VOICEDROP_MLX_MODEL", "mlx-community/whisper-small-mlx"
        )

    def start_warmup(self) -> None:
        if self._warmup_started:
            return
        self._warmup_started = True
        thread = threading.Thread(
            target=self._warmup_models, name="model-warmup", daemon=True
        )
        thread.start()

    def _warmup_models(self) -> None:
        try:
            self._get_mlx_model()
            LOGGER.info(
                "Warmup finished with mlx-whisper model '%s'",
                self.mlx_model_name,
            )
        except Exception:
            LOGGER.exception("Warmup failed for mlx-whisper; faster-whisper fallback will remain")
            try:
                self._get_faster_model()
                LOGGER.info(
                    "Warmup finished with faster-whisper model '%s'",
                    self.faster_model_name,
                )
            except Exception:
                LOGGER.exception("Warmup failed for faster-whisper fallback")

    def _get_mlx_model(self):
        import mlx.core as mx
        from mlx_whisper.load_models import load_model
        from mlx_whisper.transcribe import ModelHolder

        model = load_model(self.mlx_model_name, dtype=mx.float16)
        ModelHolder.model = model
        ModelHolder.model_path = self.mlx_model_name
        return model

    def _get_faster_model(self):
        if self._faster_model is not None:
            return self._faster_model

        with self._faster_lock:
            if self._faster_model is not None:
                return self._faster_model
            from faster_whisper import WhisperModel

            LOGGER.info(
                "Loading faster-whisper model '%s' (compute_type=%s)",
                self.faster_model_name,
                self.faster_compute_type,
            )
            self._faster_model = WhisperModel(
                self.faster_model_name,
                device="cpu",
                compute_type=self.faster_compute_type,
                cpu_threads=max(1, (os.cpu_count() or 4) - 1),
                num_workers=1,
            )
            return self._faster_model

    def _run_faster_whisper_pass(
        self,
        audio_path: Path,
        *,
        vad_filter: bool,
        beam_size: int,
        label: str,
    ) -> tuple[str, str, list]:
        model = self._get_faster_model()
        LOGGER.info(
            "Transcribing with faster-whisper (%s): %s",
            label,
            audio_path,
        )
        raw_segments, info = model.transcribe(
            str(audio_path),
            language=self.language,
            task="transcribe",
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt or None,
        )
        seg_list = [{"start": s.start, "end": s.end, "text": s.text} for s in raw_segments]
        text = "".join(s["text"] for s in seg_list).strip()
        language = getattr(info, "language", "unknown")
        return text, language, seg_list

    def _transcribe_with_faster_whisper(self, audio_path: Path) -> tuple[str, str, str]:
        attempts = [
            {"vad_filter": True, "beam_size": 1, "label": "vad-on-fast"},
            {"vad_filter": False, "beam_size": 1, "label": "vad-off-fast"},
            {"vad_filter": False, "beam_size": 5, "label": "vad-off-beam5"},
        ]

        last_language = "unknown"
        for attempt in attempts:
            text, language, segments = self._run_faster_whisper_pass(audio_path, **attempt)
            last_language = language
            if text:
                return text, language, f"faster-whisper:{attempt['label']}", segments
            LOGGER.warning(
                "faster-whisper returned empty text for %s",
                attempt["label"],
            )

        return "", last_language, "faster-whisper", []

    def _transcribe_with_mlx(self, audio_path: Path) -> tuple[str, str, str, list]:
        import mlx_whisper

        LOGGER.info("Transcribing with mlx-whisper: %s", audio_path)
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=self.mlx_model_name,
            verbose=False,
            language=self.language,
            task="transcribe",
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.initial_prompt or None,
        )
        segments = [
            {"start": s.get("start", 0.0), "end": s.get("end", 0.0), "text": s.get("text", "")}
            for s in result.get("segments", [])
        ]
        text = str(result.get("text", "")).strip()
        language = str(result.get("language", "unknown"))
        return text, language, "mlx-whisper", segments

    def transcribe(self, audio_path: Path) -> tuple[str, str, str, list]:
        errors: list[str] = []
        for backend in (self._transcribe_with_mlx, self._transcribe_with_faster_whisper):
            try:
                text, language, backend_name, segments = backend(audio_path)
                if text:
                    normalized_text = normalize_transcript_text(
                        text,
                        language,
                        glossary=self.term_glossary,
                    )
                    if normalized_text != text:
                        LOGGER.info("Normalized transcript output for %s", language)
                    if is_filtered_hallucination(normalized_text):
                        errors.append(f"{backend_name}: hallucination filter")
                        LOGGER.warning(
                            "Dropped transcript because it matched a filtered phrase: %s",
                            normalized_text,
                        )
                        continue
                    text = normalized_text
                    return text, language, backend_name, segments
                errors.append(f"{backend_name}: empty transcript")
                LOGGER.warning("Backend returned empty transcript: %s", backend_name)
            except Exception as exc:
                backend_name = backend.__name__.replace("_transcribe_with_", "")
                LOGGER.exception("Backend failed: %s", backend_name)
                errors.append(f"{backend_name}: {exc}")
        if errors and all(
            "empty transcript" in error or "hallucination filter" in error for error in errors
        ):
            raise NoSpeechDetectedError("No speech was detected in the recording.")
        raise RuntimeError("All transcription backends failed: " + " | ".join(errors))


def format_live_transcript(text: str, language: str, segments: list, glossary: dict[str, str] | None = None) -> str:
    base_text = normalize_transcript_text(text, language, glossary=glossary)
    is_japanese = language == "ja" or bool(JAPANESE_CHAR_PATTERN.search(base_text))
    is_latin = language == "en" or bool(LATIN_CHAR_PATTERN.search(base_text))
    if not segments or not (is_japanese or is_latin):
        return base_text

    comma_char = "、" if is_japanese else ","
    sentence_char = "。" if is_japanese else "."
    sentence_break = "\n" if is_japanese else " "
    paragraph_break = "\n\n"

    parts: list[str] = []
    prev_end: float | None = None

    for seg in segments:
        seg_text = normalize_transcript_text(
            str(seg.get("text", "")).strip(),
            language,
            glossary=glossary,
            add_terminal_punctuation=False,
        )
        if not seg_text:
            prev_end = seg.get("end", prev_end)
            continue

        if parts and prev_end is not None:
            current_start = float(seg.get("start", prev_end))
            gap = max(0.0, current_start - prev_end)
            last = parts[-1]

            if gap >= LIVE_PARAGRAPH_GAP_SECONDS:
                if not re.search(r"[。！？.!?]$", last):
                    parts[-1] = last + sentence_char
                parts.append(paragraph_break)
            elif gap >= LIVE_SENTENCE_GAP_SECONDS:
                if not re.search(r"[。！？.!?]$", last):
                    parts[-1] = last + sentence_char
                parts.append(sentence_break)
            elif gap >= LIVE_COMMA_GAP_SECONDS:
                visible_chars = len(re.sub(r"[\s、。！？,.;:!?]", "", seg_text))
                if visible_chars >= LIVE_COMMA_MIN_CHARS and not re.search(r"[、。！？,.;:!?]$", last):
                    parts[-1] = last + comma_char

        parts.append(seg_text)
        prev_end = float(seg.get("end", prev_end if prev_end is not None else 0.0))

    formatted = "".join(parts).strip()
    formatted = normalize_transcript_text(formatted, language, glossary=glossary)
    if not re.search(r"[、。,.;:!?]", formatted) and "\n" not in formatted:
        return base_text
    return formatted


def save_recording(recording: RecordingResult) -> tuple[Path, Path]:
    ensure_dirs()
    temp_path = Path(tempfile.gettempdir()) / f"voicedrop_{recording.started_stamp}.wav"
    merge_wav_segments(recording.segment_paths, temp_path)
    shutil.copyfile(temp_path, LAST_AUDIO_FILE)

    archive_mp3_path = ARCHIVED_AUDIO_DIR / f"VoiceDrop_{recording.started_stamp}.mp3"
    archive_wav_path = ARCHIVED_AUDIO_DIR / f"VoiceDrop_{recording.started_stamp}.wav"
    archive_mp3_path.unlink(missing_ok=True)
    archive_wav_path.unlink(missing_ok=True)

    try:
        encode_mp3_archive(temp_path, archive_mp3_path)
        archive_path = archive_mp3_path
    except Exception:
        LOGGER.exception("Failed to encode MP3 archive; keeping WAV instead")
        shutil.copyfile(temp_path, archive_wav_path)
        archive_path = archive_wav_path

    try:
        shutil.rmtree(recording.session_dir)
    except Exception:
        LOGGER.exception("Failed to remove in-progress session: %s", recording.session_dir)

    LOGGER.info("Saved merged audio to %s", temp_path)
    LOGGER.info("Archived audio to %s", archive_path)
    return temp_path, archive_path


def cleanup_recording_session(recording: RecordingResult) -> None:
    try:
        shutil.rmtree(recording.session_dir)
    except FileNotFoundError:
        return
    except Exception:
        LOGGER.exception("Failed to clean up discarded session: %s", recording.session_dir)


def save_transcript(
    text: str,
    *,
    stamp: str | None = None,
    label: str | None = None,
    directory: Path | None = None,
) -> Path:
    ensure_dirs()
    stamp = stamp or utc_timestamp()
    directory = directory or TRANSCRIPTS_DIR
    base_name = f"VoiceDrop_{stamp}"
    if label:
        base_name += f"_{sanitize_filename_component(label, fallback='speech', max_length=32)}"
    path = make_unique_path(directory / f"{base_name}.txt")
    path.write_text(text + "\n", encoding="utf-8")
    LAST_TRANSCRIPT_FILE.write_text(text, encoding="utf-8")
    LOGGER.info("Saved transcript to %s", path)
    return path


def save_metadata(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_self_check() -> int:
    setup_logging()
    ensure_dirs()

    result: dict[str, object] = {
        "python": sys.executable,
        "app_dir": str(APP_DIR),
        "transcripts_dir": str(TRANSCRIPTS_DIR),
        "log_file": str(LOG_FILE),
        "shortcut_trusted": None,
        "default_device": None,
        "devices": [],
        "imports": {},
    }

    for module_name in ("rumps", "sounddevice", "numpy", "scipy"):
        try:
            __import__(module_name)
            result["imports"][module_name] = "ok"
        except Exception as exc:
            result["imports"][module_name] = f"error: {exc}"

    for optional_name in ("faster_whisper", "mlx_whisper"):
        try:
            __import__(optional_name)
            result["imports"][optional_name] = "ok"
        except Exception as exc:
            result["imports"][optional_name] = f"error: {exc}"

    try:
        result["shortcut_trusted"] = bool(
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False})
        )
    except Exception as exc:
        result["shortcut_trusted"] = f"error: {exc}"

    try:
        devices = sd.query_devices()
        result["devices"] = [str(device) for device in devices]
        result["default_device"] = list(sd.default.device)
    except Exception as exc:
        result["audio_error"] = str(exc)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


class RightOptionEventTap:
    def __init__(self, on_press) -> None:
        self.on_press = on_press
        self._thread: threading.Thread | None = None
        self._tap = None
        self._run_loop = None
        self._source = None
        self._right_option_down = False

    @property
    def is_running(self) -> bool:
        return self._tap is not None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="shortcut-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._run_loop is not None:
            CFRunLoopStop(self._run_loop)

    def _run(self) -> None:
        try:
            mask = CGEventMaskBit(kCGEventFlagsChanged)
            self._tap = CGEventTapCreate(
                kCGSessionEventTap,
                kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly,
                mask,
                self._callback,
                None,
            )
            if self._tap is None:
                LOGGER.error("Failed to create CGEventTap for Right Option shortcut")
                return

            self._source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._run_loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self._run_loop, self._source, kCFRunLoopCommonModes)
            CGEventTapEnable(self._tap, True)
            LOGGER.info("Right Option CGEventTap started")
            CFRunLoopRun()
        except Exception:
            LOGGER.exception("Right Option CGEventTap crashed")
        finally:
            self._tap = None
            self._source = None
            self._run_loop = None
            self._right_option_down = False

    def _callback(self, _proxy, event_type, event, _refcon):
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            LOGGER.warning("Right Option CGEventTap was disabled; re-enabling")
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
            return event

        if event_type != kCGEventFlagsChanged:
            return event

        keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
        if keycode != RIGHT_OPTION_KEYCODE:
            return event

        is_down = bool(
            CGEventSourceKeyState(
                kCGEventSourceStateCombinedSessionState, RIGHT_OPTION_KEYCODE
            )
        )
        if not is_down:
            is_down = bool(CGEventGetFlags(event) & kCGEventFlagMaskAlternate)

        if is_down and not self._right_option_down:
            self._right_option_down = True
            LOGGER.info("Right Option shortcut pressed")
            AppHelper.callAfter(self.on_press)
        elif not is_down:
            self._right_option_down = False

        return event


class VoiceDropApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(APP_NAME, title="VD", quit_button="Quit VoiceDrop")
        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()
        self._job_queue: queue.PriorityQueue[TranscriptionJob] = queue.PriorityQueue()
        self._job_counter = itertools.count()
        self._job_state_lock = threading.Lock()
        self._queued_job_count = 0
        self._active_job: TranscriptionJob | None = None
        self._recording_transition_lock = threading.Lock()
        self._recording_transition: str | None = None
        self._recording_timer_lock = threading.Lock()
        self._recording_timer_cancel: threading.Event | None = None
        self._recording_timer_stamp: str | None = None
        self.shortcut_monitor = RightOptionEventTap(self.toggle_recording_from_shortcut)
        self._spinner_thread = threading.Thread(
            target=self._spinner_loop,
            name="spinner",
            daemon=True,
        )
        self._worker_thread = threading.Thread(
            target=self._transcription_worker_loop,
            name="transcription-worker",
            daemon=True,
        )
        self.start_button = rumps.MenuItem("Start Recording", callback=self.start_recording)
        self.stop_button = rumps.MenuItem("Stop Recording", callback=self.stop_recording)
        self.shortcut_status_button = rumps.MenuItem(
            "Shortcut: Right Option (toggle)", callback=self.show_shortcut_help
        )
        self.shortcut_permission_button = rumps.MenuItem(
            "Request Shortcut Permission", callback=self.request_shortcut_permission
        )
        self.open_transcripts_button = rumps.MenuItem(
            "Open Transcripts Folder", callback=self.open_transcripts
        )
        self.open_logs_button = rumps.MenuItem("Open Logs", callback=self.open_logs)
        self.copy_last_button = rumps.MenuItem(
            "Copy Last Transcript", callback=self.copy_last_transcript
        )
        self.self_check_button = rumps.MenuItem("Self Check", callback=self.self_check)

        self.model_small_item = rumps.MenuItem(
            "  Small (~300MB, faster)",
            callback=lambda _: self._switch_model("mlx-community/whisper-small-mlx"),
        )
        self.model_large_item = rumps.MenuItem(
            "  Large v3 Turbo (~1.5GB, best accuracy)",
            callback=lambda _: self._switch_model("mlx-community/whisper-large-v3-turbo"),
        )
        self.model_menu = rumps.MenuItem("Model")
        self.model_menu.add(self.model_small_item)
        self.model_menu.add(self.model_large_item)
        self._update_model_checkmarks()

        self.menu = [
            self.start_button,
            self.stop_button,
            None,
            self.shortcut_status_button,
            self.shortcut_permission_button,
            None,
            self.open_transcripts_button,
            self.open_logs_button,
            self.copy_last_button,
            self.self_check_button,
            None,
            self.model_menu,
        ]

        self._start_shortcut_monitor()
        self._refresh_menu_state()
        self._notify_recovery_sessions()
        self._worker_thread.start()
        self.transcriber.start_warmup()
        self._spinner_thread.start()
        send_notification("Ready", "VoiceDrop is running in the menu bar.")

    def _set_title(self, value: str) -> None:
        self.title = value

    def _queue_state(self) -> tuple[int, TranscriptionJob | None]:
        with self._job_state_lock:
            return self._queued_job_count, self._active_job

    def _recording_transition_state(self) -> str | None:
        with self._recording_transition_lock:
            return self._recording_transition

    def _begin_recording_transition(self, transition: str) -> bool:
        with self._recording_transition_lock:
            if self._recording_transition is not None:
                return False
            self._recording_transition = transition
            return True

    def _clear_recording_transition(self) -> None:
        with self._recording_transition_lock:
            self._recording_transition = None

    def _has_pending_work(self) -> bool:
        queued_count, active_job = self._queue_state()
        return queued_count > 0 or active_job is not None

    def _cancel_recording_timeout(self) -> None:
        with self._recording_timer_lock:
            cancel_event = self._recording_timer_cancel
            self._recording_timer_cancel = None
            self._recording_timer_stamp = None
        if cancel_event is not None:
            cancel_event.set()

    def _arm_recording_timeout(self) -> None:
        stamp = self.recorder.recording_stamp
        if stamp is None:
            return

        self._cancel_recording_timeout()
        cancel_event = threading.Event()
        with self._recording_timer_lock:
            self._recording_timer_cancel = cancel_event
            self._recording_timer_stamp = stamp

        def watch(expected_stamp: str, completed: threading.Event) -> None:
            if completed.wait(MAX_RECORDING_SECONDS):
                return
            LOGGER.warning(
                "Maximum recording duration reached for %s; auto-stopping",
                expected_stamp,
            )
            AppHelper.callAfter(self._auto_stop_recording, expected_stamp)

        threading.Thread(
            target=watch,
            args=(stamp, cancel_event),
            name="recording-timeout",
            daemon=True,
        ).start()

    def _auto_stop_recording(self, expected_stamp: str) -> None:
        with self._recording_timer_lock:
            active_stamp = self._recording_timer_stamp

        if active_stamp != expected_stamp:
            return
        if not self.recorder.is_recording:
            return
        if self.recorder.recording_stamp != expected_stamp:
            return
        if self._recording_transition_state() is not None:
            return

        send_notification(
            "Recording limit reached",
            "VoiceDrop stopped automatically after 60 minutes.",
        )
        self._request_stop_recording(source="auto-stop")

    def _spinner_loop(self) -> None:
        index = 0
        while True:
            if self._recording_transition_state() is not None:
                index = 0
                time.sleep(0.1)
                continue
            if self.recorder.is_recording:
                index = 0
                time.sleep(0.1)
                continue
            if self._has_pending_work():
                AppHelper.callAfter(
                    self._set_title,
                    SPINNER_FRAMES[index % len(SPINNER_FRAMES)],
                )
                index += 1
                time.sleep(0.12)
            else:
                index = 0
                time.sleep(0.2)

    def _refresh_menu_state(self) -> None:
        shortcut_ready = self._shortcut_is_trusted() and self.shortcut_monitor.is_running
        queued_count, active_job = self._queue_state()
        transition = self._recording_transition_state()
        self.start_button.set_callback(self.start_recording)
        self.stop_button.set_callback(self.stop_recording)
        self.start_button.state = 0
        self.stop_button.state = 1 if self.recorder.is_recording or transition == "stopping" else 0

        if transition == "starting":
            self.start_button.title = "Starting..."
        elif transition == "stopping":
            self.start_button.title = "Start Recording (busy)"
        elif self.recorder.is_recording:
            self.start_button.title = "Recording in Progress..."
        else:
            self.start_button.title = "Start Recording"

        if transition == "stopping":
            self.stop_button.title = "Stopping..."
        elif transition == "starting":
            self.stop_button.title = "Stop Recording (inactive)"
        else:
            self.stop_button.title = (
                "Stop Recording" if self.recorder.is_recording else "Stop Recording (inactive)"
            )
        self.copy_last_button.title = (
            "Copy Last Transcript"
            if LAST_TRANSCRIPT_FILE.exists()
            else "Copy Last Transcript (none yet)"
        )
        self.shortcut_status_button.title = (
            "Shortcut: Right Option (toggle)"
            if shortcut_ready
            else "Shortcut: Right Option (permission needed)"
        )
        self.shortcut_permission_button.title = (
            "Shortcut Permission OK"
            if shortcut_ready
            else "Request Shortcut Permission"
        )

    def _shortcut_is_trusted(self, prompt: bool = False) -> bool:
        try:
            return bool(
                AXIsProcessTrustedWithOptions(
                    {kAXTrustedCheckOptionPrompt: bool(prompt)}
                )
            )
        except Exception:
            LOGGER.exception("Failed to query Accessibility trust")
            return False

    def _update_model_checkmarks(self) -> None:
        current = self.transcriber.mlx_model_name
        self.model_small_item.title = (
            "✓ Small (~300MB, faster)"
            if current == "mlx-community/whisper-small-mlx"
            else "  Small (~300MB, faster)"
        )
        self.model_large_item.title = (
            "✓ Large v3 Turbo (~1.5GB, best accuracy)"
            if current == "mlx-community/whisper-large-v3-turbo"
            else "  Large v3 Turbo (~1.5GB, best accuracy)"
        )

    def _switch_model(self, model_id: str) -> None:
        if model_id == self.transcriber.mlx_model_name:
            return
        MODEL_PREF_FILE.parent.mkdir(parents=True, exist_ok=True)
        MODEL_PREF_FILE.write_text(model_id)
        label = next((lbl for mid, lbl in MODEL_OPTIONS if mid == model_id), model_id)
        send_notification("Model Switch", f"Switching to {label}. Restarting…")
        time.sleep(1.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _start_shortcut_monitor(self) -> None:
        if not self._shortcut_is_trusted():
            LOGGER.warning("Right Option shortcut needs Accessibility permission")
            send_notification(
                "Shortcut permission needed",
                "Allow Accessibility for VoiceDrop/Python to use the Right Option shortcut.",
            )
            return
        self.shortcut_monitor.start()
        LOGGER.info("Right Option shortcut monitor requested")

    def _notify_recovery_sessions(self) -> None:
        try:
            sessions = sorted(IN_PROGRESS_AUDIO_DIR.glob("*.inprogress"))
        except Exception:
            LOGGER.exception("Failed to scan in-progress audio sessions")
            return

        if not sessions:
            return

        send_notification(
            "Recovered audio fragments found",
            f"{len(sessions)} unfinished recording folder(s) are in Audio/InProgress.",
        )

    def _enqueue_job(self, job: TranscriptionJob) -> None:
        with self._job_state_lock:
            self._queued_job_count += 1
        self._job_queue.put(job)
        AppHelper.callAfter(self._refresh_menu_state)

    def _enqueue_live_job(self, audio_path: Path, archive_path: Path, stamp: str) -> None:
        job = TranscriptionJob(
            priority=0,
            sequence=next(self._job_counter),
            kind="live",
            audio_path=audio_path,
            stamp=stamp,
            archive_path=archive_path,
        )
        self._enqueue_job(job)

    def _transcription_worker_loop(self) -> None:
        while True:
            job = self._job_queue.get()
            with self._job_state_lock:
                self._queued_job_count = max(0, self._queued_job_count - 1)
                self._active_job = job
            AppHelper.callAfter(self._refresh_menu_state)
            try:
                self._process_live_job(job)
            except Exception:
                LOGGER.exception("Unexpected queued job failure: %s", job.kind)
            finally:
                with self._job_state_lock:
                    self._active_job = None
                if not self.recorder.is_recording:
                    AppHelper.callAfter(self._set_title, "VD")
                AppHelper.callAfter(self._refresh_menu_state)

    def _rename_live_archive(self, archive_path: Path, stamp: str, label: str) -> Path:
        if not archive_path.exists():
            return archive_path
        target = make_unique_path(
            archive_path.with_name(
                f"VoiceDrop_{stamp}_{sanitize_filename_component(label, fallback='speech', max_length=32)}{archive_path.suffix}"
            )
        )
        archive_path.replace(target)
        return target

    def _process_live_job(self, job: TranscriptionJob) -> None:
        audio_path = job.audio_path
        archive_path = job.archive_path or audio_path
        try:
            text, language, backend, segments = self.transcriber.transcribe(audio_path)
            if not text:
                raise NoSpeechDetectedError("No speech was detected in the recording.")

            formatted_text = format_live_transcript(
                text,
                language,
                segments,
                glossary=self.transcriber.term_glossary,
            )
            if formatted_text != text:
                LOGGER.info("Formatted live transcript for %s", language)
            text = formatted_text
            label = build_transcript_label(text, fallback="speech")
            final_archive_path = self._rename_live_archive(archive_path, job.stamp, label)
            transcript_path = save_transcript(text, stamp=job.stamp, label=label)
            copy_to_clipboard(text)
            pasted = False
            paste_error = None
            try:
                time.sleep(0.12)
                paste_into_focused_app()
                pasted = True
                LOGGER.info("Transcript pasted into focused app")
            except Exception as exc:
                paste_error = exc
                LOGGER.exception("Automatic paste failed")

            if pasted:
                send_notification(
                    "Transcript saved and pasted",
                    f"{transcript_path.name} ({language}, {backend}) | audio: {final_archive_path.name}",
                )
            else:
                send_notification(
                    "Transcript saved",
                    f"{transcript_path.name} ({language}, {backend}) | audio: {final_archive_path.name} | paste failed: {paste_error}",
                )
        except NoSpeechDetectedError as exc:
            LOGGER.info("Recording discarded after transcription: %s", exc)
            send_notification("Discarded", str(exc))
        except Exception as exc:
            LOGGER.exception("Transcription failed")
            send_notification("Transcription failed", str(exc))
        finally:
            try:
                if audio_path.exists():
                    audio_path.unlink()
            except Exception:
                LOGGER.exception("Failed to remove temp audio: %s", audio_path)

    def _start_stop_watchdog(self, completed: threading.Event) -> None:
        def watch() -> None:
            if completed.wait(STOP_OPERATION_TIMEOUT_SECONDS):
                return
            LOGGER.error(
                "Recording stop exceeded %.1f seconds; forcing restart",
                STOP_OPERATION_TIMEOUT_SECONDS,
            )
            try:
                send_notification(
                    "VoiceDrop restarting",
                    "Recording stop got stuck. VoiceDrop will relaunch automatically.",
                )
            except Exception:
                LOGGER.exception("Failed to send watchdog notification")
            os._exit(75)

        threading.Thread(
            target=watch,
            name="stop-watchdog",
            daemon=True,
        ).start()

    def _finish_start_recording(self) -> None:
        self._arm_recording_timeout()
        self._clear_recording_transition()
        self._set_title("REC")
        self._refresh_menu_state()
        send_notification("Recording", "VoiceDrop is recording from the microphone.")

    def _fail_start_recording(self, message: str) -> None:
        self._cancel_recording_timeout()
        self._clear_recording_transition()
        self._set_title("VD")
        self._refresh_menu_state()
        send_notification("Recording failed", message)

    def _finish_stop_recording(self) -> None:
        self._cancel_recording_timeout()
        self._clear_recording_transition()
        self._refresh_menu_state()

    def _discard_stop_recording(self, message: str) -> None:
        self._cancel_recording_timeout()
        self._clear_recording_transition()
        self._set_title("VD")
        self._refresh_menu_state()
        send_notification("Discarded", message)

    def _fail_stop_recording(self, title: str, message: str) -> None:
        self._cancel_recording_timeout()
        self._clear_recording_transition()
        self._set_title("VD")
        self._refresh_menu_state()
        send_notification(title, message)

    def _start_recording_worker(self, source: str) -> None:
        if self.recorder.is_recording:
            LOGGER.info("Ignoring start request via %s because recording is already active", source)
            AppHelper.callAfter(
                self._fail_start_recording,
                "VoiceDrop is already recording.",
            )
            return

        try:
            self.recorder.start()
        except Exception as exc:
            LOGGER.exception("Failed to start recording")
            AppHelper.callAfter(self._fail_start_recording, str(exc))
            return

        LOGGER.info("Recording started via %s", source)
        AppHelper.callAfter(self._finish_start_recording)

    def _stop_recording_worker(self, source: str) -> None:
        completed = threading.Event()
        self._start_stop_watchdog(completed)
        if not self.recorder.is_recording:
            LOGGER.info("Ignoring stop request via %s because recording is not active", source)
            completed.set()
            AppHelper.callAfter(
                self._fail_stop_recording,
                "Not recording",
                "There is no active recording to stop.",
            )
            return

        try:
            result = self.recorder.stop()
        except Exception as exc:
            LOGGER.exception("Failed to stop recording")
            completed.set()
            AppHelper.callAfter(self._fail_stop_recording, "Stop failed", str(exc))
            return

        if result.duration_seconds < MIN_RECORDING_SECONDS or not result.segment_paths:
            LOGGER.info("Short recording discarded via %s", source)
            cleanup_recording_session(result)
            completed.set()
            AppHelper.callAfter(self._discard_stop_recording, "Recording was too short.")
            return

        if is_effectively_silent_metrics(result.peak, result.rms, result.active_ratio):
            LOGGER.info("Silent recording discarded via %s", source)
            cleanup_recording_session(result)
            completed.set()
            AppHelper.callAfter(self._discard_stop_recording, "No speech was detected.")
            return

        try:
            audio_path, archive_path = save_recording(result)
        except Exception as exc:
            LOGGER.exception("Failed to save recording")
            completed.set()
            AppHelper.callAfter(self._fail_stop_recording, "Save failed", str(exc))
            return

        LOGGER.info("Recording stopped via %s; queueing transcription", source)
        self._enqueue_live_job(audio_path, archive_path, result.started_stamp)
        completed.set()
        AppHelper.callAfter(self._finish_stop_recording)

    def _request_start_recording(self, source: str) -> None:
        if self.recorder.is_recording:
            send_notification("Already recording", "VoiceDrop is already recording.")
            return
        if not self._begin_recording_transition("starting"):
            LOGGER.info("Ignoring start request via %s during transition", source)
            return
        self._set_title("...")
        self._refresh_menu_state()
        threading.Thread(
            target=self._start_recording_worker,
            args=(source,),
            name="recording-start",
            daemon=True,
        ).start()

    def start_recording(self, _) -> None:
        self._request_start_recording(source="menu")

    def _request_stop_recording(self, source: str) -> None:
        if not self.recorder.is_recording:
            if self._recording_transition_state() == "stopping":
                LOGGER.info("Ignoring extra stop request via %s while stopping", source)
                return
            send_notification("Not recording", "There is no active recording to stop.")
            return
        if not self._begin_recording_transition("stopping"):
            LOGGER.info("Ignoring stop request via %s during transition", source)
            return
        self._cancel_recording_timeout()
        self._set_title("STP")
        self._refresh_menu_state()
        threading.Thread(
            target=self._stop_recording_worker,
            args=(source,),
            name="recording-stop",
            daemon=True,
        ).start()

    def stop_recording(self, _) -> None:
        self._request_stop_recording(source="menu")

    def toggle_recording_from_shortcut(self) -> None:
        if self._recording_transition_state() is not None:
            LOGGER.info("Ignoring shortcut press during recording transition")
            return
        if self.recorder.is_recording:
            self._request_stop_recording(source="shortcut")
        else:
            self._request_start_recording(source="shortcut")

    def open_transcripts(self, _) -> None:
        open_in_finder(TRANSCRIPTS_DIR)

    def open_logs(self, _) -> None:
        open_in_finder(LOG_DIR)

    def copy_last_transcript(self, _) -> None:
        if not LAST_TRANSCRIPT_FILE.exists():
            send_notification("Nothing to copy", "No transcript has been created yet.")
            return
        text = LAST_TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
        if not text:
            send_notification("Nothing to copy", "The last transcript was empty.")
            return
        copy_to_clipboard(text)
        send_notification("Copied", "The last transcript is now on the clipboard.")

    def self_check(self, _) -> None:
        try:
            devices = sd.query_devices()
            send_notification(
                "Self check OK",
                f"{len(devices)} audio devices detected. Log: {LOG_FILE.name}",
            )
        except Exception as exc:
            send_notification("Self check failed", str(exc))

    def show_shortcut_help(self, _) -> None:
        if self._shortcut_is_trusted():
            send_notification(
                "Shortcut ready",
                "Press Right Option once to start recording, and again to stop.",
            )
        else:
            send_notification(
                "Shortcut permission needed",
                "Open System Settings and allow Accessibility for VoiceDrop/Python.",
            )

    def request_shortcut_permission(self, _) -> None:
        if self._shortcut_is_trusted(prompt=True):
            self._start_shortcut_monitor()
            send_notification("Shortcut permission OK", "Right Option shortcut is ready.")
        else:
            send_notification(
                "Permission requested",
                "Approve Accessibility for VoiceDrop/Python, then try Right Option again.",
            )
        self._refresh_menu_state()


def handle_signal(signum: int, _frame) -> None:
    LOGGER.info("Received signal %s; exiting", signum)
    remove_pid_file()
    rumps.quit_application()


def ensure_single_instance() -> None:
    if not PID_FILE.exists():
        return
    try:
        existing_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        LOGGER.warning("Ignoring unreadable PID file: %s", PID_FILE)
        return

    if existing_pid != os.getpid() and is_process_alive(existing_pid):
        LOGGER.info("VoiceDrop already running with PID %s", existing_pid)
        raise SystemExit(0)

    LOGGER.warning("Removing stale PID file for PID %s", existing_pid)
    PID_FILE.unlink(missing_ok=True)


def main() -> int:
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(2)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="VoiceDrop menu bar recorder")
    parser.add_argument("--self-check", action="store_true", help="print environment diagnostics")
    args = parser.parse_args()

    if args.self_check:
        return run_self_check()

    setup_logging()
    ensure_dirs()
    ensure_single_instance()
    write_pid_file()
    atexit.register(remove_pid_file)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    LOGGER.info("Starting %s from %s", APP_NAME, APP_DIR)
    app = VoiceDropApp()
    app.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        setup_logging()
        LOGGER.error("Fatal error:\n%s", traceback.format_exc())
        raise
