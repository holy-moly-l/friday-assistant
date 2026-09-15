from __future__ import annotations

import json
import gzip
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "Friday Voice Recorder"
TARGET_RATE = 22050
MIN_SECONDS = 0.45
MAX_SECONDS = 30.0
SILENCE_THRESHOLD_DB = -44.0
LEAD_TAIL_MS = 140


def resource_path(name: str) -> Path:
    """Works both from source and PyInstaller bundle."""
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / name
    return Path(__file__).resolve().parents[1] / name


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def dbfs(value: float) -> float:
    value = max(float(value), 1e-9)
    return 20.0 * math.log10(value)


def resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio.astype(np.float32, copy=False)
    g = math.gcd(src_rate, dst_rate)
    up = dst_rate // g
    down = src_rate // g
    return resample_poly(audio, up, down).astype(np.float32)


def trim_with_padding(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-7:
        return audio
    threshold = 10 ** (SILENCE_THRESHOLD_DB / 20.0)
    # Relative floor prevents room tone from becoming the "speech" boundary.
    threshold = max(threshold, peak * 0.018)
    active = np.flatnonzero(np.abs(audio) >= threshold)
    if active.size == 0:
        return audio
    pad = int(sample_rate * LEAD_TAIL_MS / 1000)
    start = max(0, int(active[0]) - pad)
    end = min(audio.size, int(active[-1]) + pad + 1)
    return audio[start:end]


def audio_metrics(audio: np.ndarray, sample_rate: int) -> dict:
    if audio.size == 0:
        return {"duration": 0.0, "peak_db": -120.0, "rms_db": -120.0, "clip_ratio": 0.0}
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    clip_ratio = float(np.mean(np.abs(audio) >= 0.995))
    return {
        "duration": audio.size / sample_rate,
        "peak_db": dbfs(peak),
        "rms_db": dbfs(rms),
        "clip_ratio": clip_ratio,
    }


@dataclass
class CorpusItem:
    id: str
    text: str
    section: str = ""


class RecorderState(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.peak = 0.0
        self.rms = 0.0
        self.recording = False


class AudioRecorder:
    def __init__(self, state: RecorderState) -> None:
        self.state = state
        self.stream: Optional[sd.InputStream] = None
        self.blocks: list[np.ndarray] = []
        self.sample_rate = TARGET_RATE
        self.device_index: Optional[int] = None
        self.started_at = 0.0

    def start(self, device_index: int, requested_rate: int) -> int:
        if self.stream is not None:
            raise RuntimeError("Запись уже идёт")
        self.blocks.clear()
        self.device_index = device_index

        info = sd.query_devices(device_index, "input")
        supported_rate = requested_rate
        try:
            sd.check_input_settings(device=device_index, channels=1, dtype="float32", samplerate=requested_rate)
        except Exception:
            supported_rate = int(round(float(info.get("default_samplerate") or 48000)))
            sd.check_input_settings(device=device_index, channels=1, dtype="float32", samplerate=supported_rate)

        self.sample_rate = supported_rate
        self.started_at = time.monotonic()
        self.state.recording = True

        def callback(indata, frames, time_info, status):
            if status:
                # PortAudio status is intentionally not fatal; audio is still kept.
                pass
            mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
            self.blocks.append(mono)
            if mono.size:
                self.state.peak = float(np.max(np.abs(mono)))
                self.state.rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))

        self.stream = sd.InputStream(
            device=device_index,
            channels=1,
            dtype="float32",
            samplerate=supported_rate,
            callback=callback,
            blocksize=0,
        )
        self.stream.start()
        return supported_rate

    def stop(self) -> tuple[np.ndarray, int]:
        if self.stream is None:
            return np.empty(0, dtype=np.float32), self.sample_rate
        try:
            self.stream.stop()
            self.stream.close()
        finally:
            self.stream = None
            self.state.recording = False
            self.state.peak = 0.0
            self.state.rms = 0.0
        if not self.blocks:
            return np.empty(0, dtype=np.float32), self.sample_rate
        return np.concatenate(self.blocks), self.sample_rate

    def abort(self) -> None:
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.blocks.clear()
        self.state.recording = False
        self.state.peak = 0.0
        self.state.rms = 0.0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 720)
        self.setMinimumSize(900, 620)

        self.corpus = self.load_corpus()
        if not self.corpus:
            raise RuntimeError("Корпус пуст")

        self.dataset_dir = app_root() / "dataset"
        self.wav_dir = self.dataset_dir / "wav"
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.wav_dir.mkdir(parents=True, exist_ok=True)

        self.session_path = self.dataset_dir / "session.json"
        self.index = 0
        self.skipped: set[str] = set()
        self.flagged: set[str] = set()
        self.auto_next = True

        self.state = RecorderState()
        self.recorder = AudioRecorder(self.state)
        self.pending_audio: Optional[np.ndarray] = None
        self.pending_metrics: Optional[dict] = None
        self.current_playing = False

        self.build_ui()
        self.load_session()
        self.refresh_devices()
        self.refresh_ui()

        self.vu_timer = QTimer(self)
        self.vu_timer.timeout.connect(self.update_vu)
        self.vu_timer.start(50)

        self.session_timer = QTimer(self)
        self.session_timer.timeout.connect(self.save_session)
        self.session_timer.start(3000)

    def load_corpus(self) -> list[CorpusItem]:
        path = resource_path("corpus.json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        return [CorpusItem(id=x["id"], text=x["text"], section=x.get("section", "")) for x in raw]

    def build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Friday Voice Recorder")
        title.setObjectName("title")
        subtitle = QLabel("Запись корпуса для собственного голоса Пятницы")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.folder_btn = QPushButton("Папка датасета")
        self.folder_btn.clicked.connect(self.choose_dataset_folder)
        header.addWidget(self.folder_btn)
        outer.addLayout(header)

        # Settings bar
        settings = QFrame()
        settings.setObjectName("panel")
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(16, 12, 16, 12)
        settings_layout.setHorizontalSpacing(10)
        settings_layout.setVerticalSpacing(8)

        settings_layout.addWidget(QLabel("Микрофон"), 0, 0)
        self.mic_combo = QComboBox()
        settings_layout.addWidget(self.mic_combo, 0, 1, 1, 3)
        self.refresh_mic_btn = QPushButton("Обновить")
        self.refresh_mic_btn.clicked.connect(self.refresh_devices)
        settings_layout.addWidget(self.refresh_mic_btn, 0, 4)

        settings_layout.addWidget(QLabel("Запись"), 1, 0)
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(["22050 Hz", "44100 Hz", "48000 Hz"])
        self.rate_combo.setCurrentText("22050 Hz")
        settings_layout.addWidget(self.rate_combo, 1, 1)

        self.auto_next_box = QCheckBox("После сохранения переходить дальше")
        self.auto_next_box.setChecked(True)
        self.auto_next_box.toggled.connect(self._set_auto_next)
        settings_layout.addWidget(self.auto_next_box, 1, 2, 1, 2)

        self.open_folder_btn = QPushButton("Открыть dataset")
        self.open_folder_btn.clicked.connect(self.open_dataset_folder)
        settings_layout.addWidget(self.open_folder_btn, 1, 4)

        outer.addWidget(settings)

        # Main phrase card
        card = QFrame()
        card.setObjectName("phraseCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 20, 26, 20)
        card_layout.setSpacing(12)

        top_line = QHBoxLayout()
        self.id_label = QLabel("TR-0001")
        self.id_label.setObjectName("utteranceId")
        self.section_label = QLabel("")
        self.section_label.setObjectName("sectionLabel")
        self.section_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_line.addWidget(self.id_label)
        top_line.addStretch(1)
        top_line.addWidget(self.section_label)
        card_layout.addLayout(top_line)

        self.text_label = QLabel("")
        self.text_label.setObjectName("phrase")
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setMinimumHeight(160)
        card_layout.addWidget(self.text_label, 1)

        self.quality_label = QLabel("Готово к записи")
        self.quality_label.setObjectName("quality")
        self.quality_label.setAlignment(Qt.AlignCenter)
        card_layout.addWidget(self.quality_label)
        outer.addWidget(card, 1)

        # VU
        vu_row = QHBoxLayout()
        vu_row.addWidget(QLabel("Микрофон"))
        self.vu = QProgressBar()
        self.vu.setRange(0, 100)
        self.vu.setValue(0)
        self.vu.setTextVisible(False)
        vu_row.addWidget(self.vu, 1)
        self.db_label = QLabel("−∞ dB")
        self.db_label.setMinimumWidth(72)
        self.db_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vu_row.addWidget(self.db_label)
        outer.addLayout(vu_row)

        # Primary controls
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.prev_btn = QPushButton("← Назад")
        self.prev_btn.clicked.connect(self.prev_item)
        controls.addWidget(self.prev_btn)

        self.record_btn = QPushButton("● Запись")
        self.record_btn.setObjectName("record")
        self.record_btn.clicked.connect(self.toggle_record)
        controls.addWidget(self.record_btn, 1)

        self.play_btn = QPushButton("▶ Прослушать")
        self.play_btn.clicked.connect(self.play_current)
        controls.addWidget(self.play_btn)

        self.redo_btn = QPushButton("Перезаписать")
        self.redo_btn.clicked.connect(self.start_recording)
        controls.addWidget(self.redo_btn)

        self.next_btn = QPushButton("Далее →")
        self.next_btn.clicked.connect(self.next_item)
        controls.addWidget(self.next_btn)
        outer.addLayout(controls)

        # Secondary controls
        secondary = QHBoxLayout()
        self.skip_btn = QPushButton("Пропустить")
        self.skip_btn.clicked.connect(self.toggle_skip)
        secondary.addWidget(self.skip_btn)
        self.flag_btn = QPushButton("⚑ Пометить проблемной")
        self.flag_btn.clicked.connect(self.toggle_flag)
        secondary.addWidget(self.flag_btn)
        secondary.addStretch(1)
        self.delete_btn = QPushButton("Удалить запись")
        self.delete_btn.clicked.connect(self.delete_current)
        secondary.addWidget(self.delete_btn)
        outer.addLayout(secondary)

        # Progress
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.corpus))
        progress_row.addWidget(self.progress, 1)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(160)
        self.progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        progress_row.addWidget(self.progress_label)
        outer.addLayout(progress_row)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Готово")

        # Shortcuts
        a_record = QAction(self)
        a_record.setShortcut(QKeySequence("Space"))
        a_record.triggered.connect(self.toggle_record)
        self.addAction(a_record)
        a_next = QAction(self)
        a_next.setShortcut(QKeySequence("Right"))
        a_next.triggered.connect(self.next_item)
        self.addAction(a_next)
        a_prev = QAction(self)
        a_prev.setShortcut(QKeySequence("Left"))
        a_prev.triggered.connect(self.prev_item)
        self.addAction(a_prev)
        a_play = QAction(self)
        a_play.setShortcut(QKeySequence("Ctrl+P"))
        a_play.triggered.connect(self.play_current)
        self.addAction(a_play)

        self.apply_theme()

    def apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0d1117; color: #e6edf3; font-family: 'Segoe UI'; font-size: 14px; }
            QLabel#title { font-size: 26px; font-weight: 700; }
            QLabel#subtitle { color: #8b949e; font-size: 13px; }
            QFrame#panel, QFrame#phraseCard { background: #161b22; border: 1px solid #30363d; border-radius: 14px; }
            QFrame#phraseCard { background: #11161d; }
            QLabel#utteranceId { color: #58a6ff; font-weight: 700; font-size: 16px; }
            QLabel#sectionLabel { color: #8b949e; font-size: 12px; }
            QLabel#phrase { font-size: 28px; font-weight: 600; padding: 18px; }
            QLabel#quality { color: #8b949e; font-size: 13px; }
            QPushButton { background: #21262d; border: 1px solid #30363d; border-radius: 9px; padding: 9px 14px; }
            QPushButton:hover { background: #30363d; }
            QPushButton:pressed { background: #1f6feb; }
            QPushButton:disabled { color: #6e7681; background: #161b22; }
            QPushButton#record { background: #da3633; border-color: #f85149; font-weight: 700; }
            QPushButton#record:hover { background: #f85149; }
            QComboBox { background: #0d1117; border: 1px solid #30363d; border-radius: 7px; padding: 7px; }
            QProgressBar { background: #21262d; border: 0; border-radius: 6px; height: 12px; }
            QProgressBar::chunk { background: #238636; border-radius: 6px; }
            QCheckBox { spacing: 8px; }
            QStatusBar { color: #8b949e; }
            """
        )

    def _set_auto_next(self, value: bool) -> None:
        self.auto_next = value
        self.save_session()

    def current_item(self) -> CorpusItem:
        return self.corpus[self.index]

    def current_path(self) -> Path:
        return self.wav_dir / f"{self.current_item().id}.wav"

    def refresh_devices(self) -> None:
        selected_data = self.mic_combo.currentData() if self.mic_combo.count() else None
        self.mic_combo.clear()
        try:
            devices = sd.query_devices()
            default_in = sd.default.device[0] if isinstance(sd.default.device, (tuple, list)) else None
            selected_idx = 0
            for i, d in enumerate(devices):
                if int(d.get("max_input_channels", 0)) <= 0:
                    continue
                name = str(d.get("name", f"Device {i}"))
                hostapi = sd.query_hostapis(int(d.get("hostapi", 0))).get("name", "")
                self.mic_combo.addItem(f"{name} — {hostapi}", i)
                if selected_data == i or (selected_data is None and default_in == i):
                    selected_idx = self.mic_combo.count() - 1
            if self.mic_combo.count():
                self.mic_combo.setCurrentIndex(selected_idx)
            else:
                self.mic_combo.addItem("Микрофоны не найдены", None)
        except Exception as exc:
            self.mic_combo.addItem(f"Ошибка: {exc}", None)

    def requested_rate(self) -> int:
        return int(self.rate_combo.currentText().split()[0])

    def start_recording(self) -> None:
        if self.recorder.stream is not None:
            return
        device = self.mic_combo.currentData()
        if device is None:
            QMessageBox.warning(self, "Нет микрофона", "Выбери доступный микрофон.")
            return
        sd.stop()
        self.pending_audio = None
        try:
            actual = self.recorder.start(int(device), self.requested_rate())
        except Exception as exc:
            QMessageBox.critical(self, "Не удалось начать запись", str(exc))
            return
        self.record_btn.setText("■ Стоп")
        self.quality_label.setText(f"Идёт запись • устройство {actual} Hz")
        self.statusBar().showMessage("Запись…  Пробел — остановить")
        self.lock_navigation(True)

    def stop_recording(self) -> None:
        audio, rate = self.recorder.stop()
        self.record_btn.setText("● Запись")
        self.lock_navigation(False)
        if audio.size == 0:
            self.quality_label.setText("Запись пустая")
            return
        audio = resample_audio(audio, rate, TARGET_RATE)
        audio = trim_with_padding(audio, TARGET_RATE)
        metrics = audio_metrics(audio, TARGET_RATE)
        self.pending_audio = audio
        self.pending_metrics = metrics

        if metrics["duration"] < MIN_SECONDS:
            self.quality_label.setText("⚠ Слишком короткая запись — лучше перезаписать")
            self.statusBar().showMessage("Запись не сохранена: слишком короткая")
            return
        if metrics["duration"] > MAX_SECONDS:
            self.quality_label.setText("⚠ Очень длинная запись — проверь паузы и текст")
        if metrics["clip_ratio"] > 0.001:
            self.quality_label.setText("⚠ Обнаружен клиппинг — убавь усиление микрофона и перезапиши")
            self.statusBar().showMessage("Запись не сохранена из-за клиппинга")
            return
        if metrics["rms_db"] < -36:
            self.quality_label.setText("⚠ Запись тихая, но сохранена. Лучше проверить микрофон.")

        self.save_pending_audio()

    def save_pending_audio(self) -> None:
        if self.pending_audio is None:
            return
        path = self.current_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, self.pending_audio, TARGET_RATE, subtype="PCM_16")
        self.write_metadata()
        metrics = self.pending_metrics or audio_metrics(self.pending_audio, TARGET_RATE)
        self.quality_label.setText(
            f"✓ Сохранено • {metrics['duration']:.1f} с • пик {metrics['peak_db']:.1f} dBFS • RMS {metrics['rms_dc']:.1f} dBFS"
        )
        self.statusBar().showMessage(f"Сохранено: {path.name}")
        self.pending_audio = None
        self.pending_metrics = None
        self.save_session()
        if self.auto_next and self.index < len(self.corpus) - 1:
            QTimer.singleShot(350, self.next_item)
        else:
            self.refresh_ui()

    def toggle_record(self) -> None:
        if self.recorder.stream is None:
            self.start_recording()
        else:
            self.stop_recording()

    def lock_navigation(self, locked: bool) -> None:
        for w in [self.prev_btn, self.next_btn, self.play_btn, self.redo_btn, self.skip_btn, self.flag_btn, self.delete_btn, self.folder_btn, self.mic_combo]:
            w.setDisabled(locked)

    def update_vu(self) -> None:
        if not self.state.recording:
            self.vu.setValue(0)
            self.db_label.setText("−∞ dB")
            return
        peak = self.state.peak
        d = dbfs(peak)
        # Map -60..0 dB onto 0..100
        pct = int(max(0, min(100, (d + 60.0) / 60.0 * 100.0)))
        self.vu.setValue(pct)
        self.db_label.setText(f"{d:.1f} dB")
        elapsed = time.monotonic() - self.recorder.started_at
        self.quality_label.setText(f"Идёт запись • {elapsed:.1f} с")
        if elapsed >= MAX_SECONDS + 5:
            self.stop_recording()

    def play_current(self) -> None:
        path = self.current_path()
        if not path.exists():
            QMessageBox.information(self, "Нет записи", "Для этой фразы ещё нет WAV-файла.")
            return
        try:
            sd.stop()
            data, rate = sf.read(path, dtype="float32")
            sd.play(data, rate)
            self.statusBar().showMessage(f"Воспроизведение: {path.name}")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка воспроизведения", str(exc))

    def prev_item(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.refresh_ui()
            self.save_session()

    def next_item(self) -> None:
        if self.index < len(self.corpus) - 1:
            self.index += 1
            self.refresh_ui()
            self.save_session()

    def toggle_skip(self) -> None:
        item_id = self.current_item().id
        if item_id in self.skipped:
            self.skipped.remove(item_id)
        else:
            self.skipped.add(item_id)
        self.save_session()
        self.refresh_ui()
        if item_id in self.skipped and self.index < len(self.corpus) - 1:
            self.next_item()

    def toggle_flag(self) -> None:
        item_id = self.current_item().id
        if item_id in self.flagged:
            self.flagged.remove(item_id)
        else:
            self.flagged.add(item_id)
        self.save_session()
        self.refresh_ui()

    def delete_current(self) -> None:
        path = self.current_path()
        if not path.exists():
            return
        if QMessageBox.question(self, "Удалить запись?", f"Удалить {path.name}?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        path.unlink(missing_ok=True)
        self.write_metadata()
        self.refresh_ui()
        self.statusBar().showMessage("Запись удалена")

    def count_recorded(self) -> int:
        return sum((self.wav_dir / f"{x.id}.wav").exists() for x in self.corpus)

    def write_metadata(self) -> None:
        lines = []
        for item in self.corpus:
            wav = self.wav_dir / f"{item.id}.wav"
            if wav.exists():
                text = item.text.replace("\n", " ").replace("|", " ")
                lines.append(f"{item.id}.wav|{text}")
        (self.dataset_dir / "metadata.csv").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def refresh_ui(self) -> None:
        item = self.current_item()
        path = self.current_path()
        self.id_label.setText(item.id)
        self.section_label.setText(item.section)
        self.text_label.setText(item.text)

        if path.exists():
            try:
                info = sf.info(path)
                data, _ = sf.read(path, dtype="float32")
                m = audio_metrics(np.asarray(data, dtype=np.float32).reshape(-1), int(info.samplerate))
                self.quality_label.setText(f"✓ Уже записано • {m['duration']:.1f} с • {m['peak_db']:.1f} dBFS")
            except Exception:
                self.quality_label.setText("✓ Уже записано")
        elif item.id in self.skipped:
            self.quality_label.setText("Пропущено")
        else:
            self.quality_label.setText("Готово к записи • Пробел — начать")

        self.skip_btn.setText("Вернуть" if item.id in self.skipped else "Пропустить")
        self.flag_btn.setText("⚑ Снять отметку" if item.id in self.flagged else "⚑ Пометить проблемной")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.corpus) - 1)
        self.play_btn.setEnabled(path.exists())
        self.delete_btn.setEnabled(path.exists())

        recorded = self.count_recorded()
        self.progress.setValue(recorded)
        percent = recorded / len(self.corpus) * 100
        self.progress_label.setText(f"{recorded} / {len(self.corpus)}  ({percent:.1f}%)")
        self.setWindowTitle(f"{APP_NAME} — {item.id} — {self.index + 1}/{len(self.corpus)}")

    def save_session(self) -> None:
        data = {
            "index": self.index,
            "skipped": sorted(self.skipped),
            "flagged": sorted(self.flagged),
            "auto_next": self.auto_next,
            "dataset_dir": str(self.dataset_dir),
        }
        try:
            self.dataset_dir.mkdir(parents=True, exist_ok=True)
            self.session_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def load_session(self) -> None:
        if not self.session_path.exists():
            return
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
            self.index = max(0, min(int(data.get("index", 0)), len(self.corpus) - 1))
            self.skipped = set(data.get("skipped", []))
            self.flagged = set(data.get("flagged", []))
            self.auto_next = bool(data.get("auto_next", True))
            self.auto_next_box.setChecked(self.auto_next)
        except Exception:
            pass

    def choose_dataset_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Выбери папку для датасета", str(self.dataset_dir))
        if not chosen:
            return
        self.dataset_dir = Path(chosen)
        self.wav_dir = self.dataset_dir / "wav"
        self.wav_dir.mkdir(parents=True, exist_ok=True)
        self.session_path = self.dataset_dir / "session.json"
        self.skipped.clear()
        self.flagged.clear()
        self.index = 0
        self.load_session()
        self.write_metadata()
        self.refresh_ui()
        self.statusBar().showMessage(f"Dataset: {self.dataset_dir}")

    def open_dataset_folder(self) -> None:
        path = self.dataset_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось открыть папку", str(exc))

    def closeEvent(self, event) -> None:
        self.save_session()
        self.recorder.abort()
        sd.stop()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
