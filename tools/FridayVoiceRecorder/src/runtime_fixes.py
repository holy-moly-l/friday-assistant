from __future__ import annotations

import csv
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QMessageBox


class _StopBridge(QObject):
    finished = Signal(object, int)
    failed = Signal(str)


def install_hotfixes(fvr) -> None:
    """Apply runtime fixes without changing the main recorder implementation.

    Fixes:
    - stopping PortAudio no longer blocks the Qt GUI thread;
    - typo rms_dc -> rms_db after a recording is saved;
    - Excel-readable UTF-8 CSV is generated alongside Piper metadata.
    """

    def write_metadata(self) -> None:
        piper_lines: list[str] = []
        excel_rows: list[tuple[str, str]] = []

        for item in self.corpus:
            wav = self.wav_dir / f"{item.id}.wav"
            if not wav.exists():
                continue
            text = item.text.replace("\n", " ").replace("|", " ")
            piper_lines.append(f"{item.id}.wav|{text}")
            excel_rows.append((f"{item.id}.wav", text))

        warnings: list[str] = []

        try:
            (self.dataset_dir / "metadata_piper.csv").write_text(
                "\n".join(piper_lines) + ("\n" if piper_lines else ""),
                encoding="utf-8",
            )
        except PermissionError:
            warnings.append("metadata_piper.csv занят другой программой")

        try:
            with (self.dataset_dir / "metadata.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(["audio", "text"])
                writer.writerows(excel_rows)
        except PermissionError:
            warnings.append("metadata.csv открыт в Excel")

        self._metadata_warnings = warnings

    def save_pending_audio(self) -> None:
        if self.pending_audio is None:
            return
        path = self.current_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fvr.sf.write(path, self.pending_audio, fvr.TARGET_RATE, subtype="PCM_16")
        self.write_metadata()
        metrics = self.pending_metrics or fvr.audio_metrics(self.pending_audio, fvr.TARGET_RATE)
        self.quality_label.setText(
            f"✓ Сохранено • {metrics['duration']:.1f} с • пик {metrics['peak_db']:.1f} dBFS • RMS {metrics['rms_db']:.1f} dBFS"
        )
        metadata_warnings = getattr(self, "_metadata_warnings", [])
        if metadata_warnings:
            self.statusBar().showMessage(
                f"Сохранено: {path.name} • метаданные обновятся после закрытия Excel"
            )
        else:
            self.statusBar().showMessage(f"Сохранено: {path.name}")
        self.pending_audio = None
        self.pending_metrics = None
        self.save_session()
        if self.auto_next and self.index < len(self.corpus) - 1:
            QTimer.singleShot(350, self.next_item)
        else:
            self.refresh_ui()

    def _finish_stop(self, audio, rate: int) -> None:
        self._stop_in_progress = False
        self.record_btn.setEnabled(True)
        self.record_btn.setText("● Запись")
        self.lock_navigation(False)

        if audio is None or not getattr(audio, "size", 0):
            self.quality_label.setText("Запись пустая")
            self.statusBar().showMessage("Запись пустая")
            return

        try:
            audio = fvr.resample_audio(audio, rate, fvr.TARGET_RATE)
            audio = fvr.trim_with_padding(audio, fvr.TARGET_RATE)
            metrics = fvr.audio_metrics(audio, fvr.TARGET_RATE)
            self.pending_audio = audio
            self.pending_metrics = metrics

            if metrics["duration"] < fvr.MIN_SECONDS:
                self.quality_label.setText("⚠ Слишком короткая запись — лучше перезаписать")
                self.statusBar().showMessage("Запись не сохранена: слишком короткая")
                return
            if metrics["duration"] > fvr.MAX_SECONDS:
                self.quality_label.setText("⚠ Очень длинная запись — проверь паузы и текст")
            if metrics["clip_ratio"] > 0.001:
                self.quality_label.setText("⚠ Обнаружен клиппинг — убавь усиление микрофона и перезапиши")
                self.statusBar().showMessage("Запись не сохранена из-за клиппинга")
                return
            if metrics["rms_db"] < -36:
                self.quality_label.setText("⚠ Запись тихая, но сохранена. Лучше проверить микрофон.")

            self.save_pending_audio()
        except Exception as exc:
            self.pending_audio = None
            self.pending_metrics = None
            self.quality_label.setText("⚠ Ошибка обработки записи")
            self.statusBar().showMessage("Ошибка обработки записи")
            QMessageBox.critical(self, "Ошибка обработки записи", str(exc))

    def _fail_stop(self, message: str) -> None:
        self._stop_in_progress = False
        self.record_btn.setEnabled(True)
        self.record_btn.setText("● Запись")
        self.lock_navigation(False)
        self.quality_label.setText("⚠ Не удалось остановить аудиопоток")
        self.statusBar().showMessage("Ошибка остановки записи")
        QMessageBox.critical(self, "Не удалось остановить запись", message)

    def stop_recording(self) -> None:
        if getattr(self, "_stop_in_progress", False):
            return
        if self.recorder.stream is None:
            return

        self._stop_in_progress = True
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Останавливаю…")
        self.quality_label.setText("Останавливаю запись…")
        self.statusBar().showMessage("Останавливаю аудиопоток…")
        self.lock_navigation(True)

        bridge = getattr(self, "_stop_bridge", None)
        if bridge is None:
            bridge = _StopBridge(self)
            bridge.finished.connect(lambda audio, rate: _finish_stop(self, audio, rate))
            bridge.failed.connect(lambda message: _fail_stop(self, message))
            self._stop_bridge = bridge

        def worker() -> None:
            try:
                audio, rate = self.recorder.stop()
                bridge.finished.emit(audio, rate)
            except Exception as exc:
                bridge.failed.emit(str(exc))

        threading.Thread(target=worker, name="FridayRecorderStop", daemon=True).start()

    fvr.MainWindow.write_metadata = write_metadata
    fvr.MainWindow.save_pending_audio = save_pending_audio
    fvr.MainWindow.stop_recording = stop_recording
