import sys
import os
import asyncio
import io
import math
import random
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, QRectF
from PyQt6.QtGui import QPainter, QColor, QFont, QIcon, QPixmap, QImage, QLinearGradient, QBrush, QPen
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QProgressBar, QGraphicsDropShadowEffect, QFrame
)

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
    )
    from winrt.windows.storage.streams import DataReader, Buffer, InputStreamOptions
    WINRT_AVAILABLE = True
except Exception:
    WINRT_AVAILABLE = False


class VisualizerWidget(QWidget):
    """Анимированный неоново-изумрудный эквалайзер в стиле Spotify Bento"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 30)
        self.bars = [0.25, 0.6, 0.9, 0.45, 0.85, 0.35, 0.7]
        self.target_bars = list(self.bars)
        self.is_playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(45)

    def set_playing(self, playing: bool):
        self.is_playing = playing
        if not playing:
            self.target_bars = [0.12] * len(self.bars)
        self.update()

    def update_animation(self):
        if self.is_playing:
            self.target_bars = [random.uniform(0.18, 1.0) for _ in range(len(self.bars))]
        for i in range(len(self.bars)):
            self.bars[i] += (self.target_bars[i] - self.bars[i]) * 0.38
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bar_count = len(self.bars)
        gap = 3
        bar_width = (w - (bar_count - 1) * gap) / bar_count

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(29, 185, 84))   # Spotify Emerald
        grad.setColorAt(1.0, QColor(30, 215, 96))   # Light Green Glow

        for i, val in enumerate(self.bars):
            bar_h = max(3.0, val * (h - 4))
            x = i * (bar_width + gap)
            y = h - bar_h
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), 2, 2)


class MusicBarWidget(QWidget):
    """Премиальный виджет рабочего стола: Spotify Emerald & Carbon"""
    def __init__(self):
        super().__init__()
        self.drag_position = QPoint()
        self.always_on_top = True
        self.demo_mode = False
        self.current_title = "Ожидание трека..."
        self.current_artist = "Spotify, Браузер, Яндекс Музыка"
        self.current_position = 0
        self.current_duration = 180
        self.is_playing = False
        self.session_manager = None
        self.current_session = None

        self.init_ui()
        self.init_media_manager()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.sync_media_state)
        self.poll_timer.start(1000)

        self.timeline_timer = QTimer(self)
        self.timeline_timer.timeout.connect(self.tick_timeline)
        self.timeline_timer.start(1000)

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 105)

        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 510, screen.height() - 175)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Главный Bento контейнер
        self.container = QFrame(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            QFrame#container {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(18, 18, 22, 0.96),
                    stop:1 rgba(24, 24, 30, 0.94));
                border: 1px solid rgba(29, 185, 84, 0.28);
                border-radius: 20px;
            }
        """)

        # Мягкое неоновое свечение
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 8)
        self.container.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self.container)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        # 1. Обложка альбома с мягкой тенью
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(66, 66)
        self.cover_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #121212, stop:1 #1DB954);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 14px;
            color: #FFFFFF;
            font-size: 26px;
        """)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("🎵")
        layout.addWidget(self.cover_label)

        # 2. Инфо о треке и прогресс-бар
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        info_layout.setContentsMargins(0, 2, 0, 2)

        # Верхний бейдж
        badge_layout = QHBoxLayout()
        badge_layout.setSpacing(6)
        
        self.badge_lbl = QLabel("● NOW PLAYING", self)
        self.badge_lbl.setStyleSheet("color: #1DB954; font-size: 9px; font-weight: 800; font-family: 'JetBrains Mono', 'Segoe UI', monospace; letter-spacing: 1px;")
        badge_layout.addWidget(self.badge_lbl)
        badge_layout.addStretch()
        info_layout.addLayout(badge_layout)

        # Название трека
        self.title_label = QLabel(self.current_title, self)
        self.title_label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 800; font-family: 'Inter', 'Segoe UI', sans-serif;")
        self.title_label.setMaximumWidth(215)
        info_layout.addWidget(self.title_label)

        # Исполнитель
        self.artist_label = QLabel(self.current_artist, self)
        self.artist_label.setStyleSheet("color: #A1A1AA; font-size: 11px; font-family: 'Inter', 'Segoe UI', sans-serif;")
        self.artist_label.setMaximumWidth(215)
        info_layout.addWidget(self.artist_label)

        # Прогресс-бар
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1DB954, stop:1 #1ED760);
                border-radius: 2px;
            }
        """)
        info_layout.addWidget(self.progress_bar)

        # Тайминг
        self.time_label = QLabel("0:00 / 0:00", self)
        self.time_label.setStyleSheet("color: #71717A; font-size: 9px; font-family: 'JetBrains Mono', monospace;")
        info_layout.addWidget(self.time_label)

        layout.addLayout(info_layout, stretch=1)

        # 3. Визуализатор
        self.visualizer = VisualizerWidget(self)
        layout.addWidget(self.visualizer)

        # 4. Кнопки управления (Pill Buttons)
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)

        ctrl_btn_style = """
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
                font-size: 13px;
                font-weight: bold;
                width: 32px;
                height: 32px;
            }
            QPushButton:hover {
                background: rgba(29, 185, 84, 0.2);
                border: 1px solid #1DB954;
                color: #1ED760;
            }
            QPushButton:pressed {
                background: #1DB954;
                color: #000000;
            }
        """

        self.prev_btn = QPushButton("⏮", self)
        self.prev_btn.setStyleSheet(ctrl_btn_style)
        self.prev_btn.setToolTip("Предыдущий трек")
        self.prev_btn.clicked.connect(self.skip_prev)
        controls_layout.addWidget(self.prev_btn)

        self.play_btn = QPushButton("▶", self)
        self.play_btn.setStyleSheet(ctrl_btn_style.replace("32px", "36px").replace("rgba(255, 255, 255, 0.06)", "#1DB954").replace("color: #FFFFFF;", "color: #000000; font-size: 15px;"))
        self.play_btn.setToolTip("Воспроизведение / Пауза")
        self.play_btn.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self.play_btn)

        self.next_btn = QPushButton("⏭", self)
        self.next_btn.setStyleSheet(ctrl_btn_style)
        self.next_btn.setToolTip("Следующий трек")
        self.next_btn.clicked.connect(self.skip_next)
        controls_layout.addWidget(self.next_btn)

        layout.addLayout(controls_layout)

        # 5. Утилиты
        util_layout = QVBoxLayout()
        util_layout.setSpacing(4)

        util_btn_style = """
            QPushButton {
                background: transparent;
                color: #71717A;
                border: none;
                font-size: 11px;
                padding: 2px;
            }
            QPushButton:hover {
                color: #FFFFFF;
            }
        """

        self.demo_btn = QPushButton("⚡", self)
        self.demo_btn.setStyleSheet(util_btn_style)
        self.demo_btn.setToolTip("Демонстрационный трек")
        self.demo_btn.clicked.connect(self.toggle_demo)
        util_layout.addWidget(self.demo_btn)

        self.pin_btn = QPushButton("📌", self)
        self.pin_btn.setStyleSheet(util_btn_style)
        self.pin_btn.setToolTip("Поверх всех окон")
        self.pin_btn.clicked.connect(self.toggle_pin)
        util_layout.addWidget(self.pin_btn)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setStyleSheet(util_btn_style)
        self.close_btn.setToolTip("Закрыть")
        self.close_btn.clicked.connect(self.close)
        util_layout.addWidget(self.close_btn)

        layout.addLayout(util_layout)
        main_layout.addWidget(self.container)

    def init_media_manager(self):
        if WINRT_AVAILABLE:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.session_manager = loop.run_until_complete(MediaManager.request_async())
            except Exception:
                pass

    def sync_media_state(self):
        if self.demo_mode or not WINRT_AVAILABLE or not self.session_manager:
            return

        try:
            session = self.session_manager.get_current_session()
            self.current_session = session

            if not session:
                if not self.demo_mode:
                    self.title_label.setText("Ожидание медиапотока...")
                    self.artist_label.setText("Запустите трек в любой программе")
                    self.play_btn.setText("▶")
                    self.visualizer.set_playing(False)
                    self.badge_lbl.setText("● IDLE")
                    self.badge_lbl.setStyleSheet("color: #71717A; font-size: 9px; font-weight: 800; font-family: 'JetBrains Mono', monospace;")
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            info = loop.run_until_complete(session.try_get_media_properties_async())
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()

            if info:
                title = info.title if info.title else "Без названия"
                artist = info.artist if info.artist else "Неизвестный исполнитель"
                self.title_label.setText(title)
                self.artist_label.setText(artist)

                if info.thumbnail:
                    stream = loop.run_until_complete(info.thumbnail.open_read_async())
                    size = stream.size
                    if size > 0:
                        reader = DataReader(stream)
                        loop.run_until_complete(reader.load_async(size))
                        byte_buf = bytearray(size)
                        reader.read_bytes(byte_buf)
                        qimg = QImage()
                        if qimg.loadFromData(bytes(byte_buf)):
                            pixmap = QPixmap.fromImage(qimg)
                            self.cover_label.setPixmap(pixmap.scaled(
                                66, 66,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation
                            ))
                            self.cover_label.setText("")

            if playback:
                is_playing = (playback.playback_status == PlaybackStatus.PLAYING)
                self.is_playing = is_playing
                self.play_btn.setText("⏸" if is_playing else "▶")
                self.visualizer.set_playing(is_playing)
                self.badge_lbl.setText("● STREAMING LIVE" if is_playing else "● PAUSED")
                self.badge_lbl.setStyleSheet(f"color: {'#1DB954' if is_playing else '#F59E0B'}; font-size: 9px; font-weight: 800; font-family: 'JetBrains Mono', monospace;")

            if timeline and timeline.end_time:
                duration_sec = timeline.end_time.total_seconds()
                pos_sec = timeline.position.total_seconds() if timeline.position else 0
                if duration_sec > 0:
                    self.current_position = int(pos_sec)
                    self.current_duration = int(duration_sec)
                    pct = int((pos_sec / duration_sec) * 100)
                    self.progress_bar.setValue(min(100, max(0, pct)))
                    self.time_label.setText(f"{self.format_time(pos_sec)} / {self.format_time(duration_sec)}")
        except Exception:
            pass

    def tick_timeline(self):
        if self.is_playing:
            self.current_position += 1
            if self.current_position > self.current_duration:
                self.current_position = 0
            pct = int((self.current_position / max(1, self.current_duration)) * 100)
            self.progress_bar.setValue(min(100, max(0, pct)))
            self.time_label.setText(f"{self.format_time(self.current_position)} / {self.format_time(self.current_duration)}")

    def toggle_demo(self):
        self.demo_mode = not self.demo_mode
        if self.demo_mode:
            self.title_label.setText("Starboy (Daft Punk Remix)")
            self.artist_label.setText("The Weeknd • Master Edition")
            self.current_position = 45
            self.current_duration = 230
            self.is_playing = True
            self.play_btn.setText("⏸")
            self.visualizer.set_playing(True)
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("⚡")
            self.badge_lbl.setText("● DEMO MASTER")
            self.badge_lbl.setStyleSheet("color: #1DB954; font-size: 9px; font-weight: 800; font-family: 'JetBrains Mono', monospace;")
            self.demo_btn.setStyleSheet("color: #1DB954; font-weight: bold; background: transparent; border: none;")
        else:
            self.demo_btn.setStyleSheet("color: #71717A; background: transparent; border: none;")
            self.sync_media_state()

    def toggle_play_pause(self):
        if self.demo_mode or not self.current_session:
            self.is_playing = not self.is_playing
            self.play_btn.setText("⏸" if self.is_playing else "▶")
            self.visualizer.set_playing(self.is_playing)
            return

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.current_session.try_toggle_play_pause_async())
            self.sync_media_state()
        except Exception:
            pass

    def skip_next(self):
        if self.demo_mode:
            self.title_label.setText("Blinding Lights (Synthwave)")
            self.artist_label.setText("The Weeknd • After Hours")
            self.current_position = 0
            self.current_duration = 200
            return

        if self.current_session:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.current_session.try_skip_next_async())
                self.sync_media_state()
            except Exception:
                pass

    def skip_prev(self):
        if self.demo_mode:
            self.title_label.setText("Midnight City (Live 2026)")
            self.artist_label.setText("M83 • Electronic Dream")
            self.current_position = 0
            self.current_duration = 244
            return

        if self.current_session:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.current_session.try_skip_previous_async())
                self.sync_media_state()
            except Exception:
                pass

    def toggle_pin(self):
        self.always_on_top = not self.always_on_top
        flags = self.windowFlags()
        if self.always_on_top:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet("color: #1DB954; font-weight: bold; background: transparent; border: none;")
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet("color: #71717A; background: transparent; border: none;")
        self.show()

    def format_time(self, seconds: float) -> str:
        s = int(seconds)
        m = s // 60
        s = s % 60
        return f"{m}:{s:02d}"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


def main():
    app = QApplication(sys.argv)
    widget = MusicBarWidget()
    widget.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
