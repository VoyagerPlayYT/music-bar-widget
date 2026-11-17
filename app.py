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

# Optional WinRT for Windows Media Control
try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus
    )
    from winrt.windows.storage.streams import DataReader, Buffer, InputStreamOptions
    WINRT_AVAILABLE = True
except Exception as e:
    WINRT_AVAILABLE = False


class VisualizerWidget(QWidget):
    """Анимированный эквалайзер-визуализатор для виджета"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 28)
        self.bars = [0.2, 0.5, 0.8, 0.4, 0.9, 0.3, 0.6]
        self.target_bars = list(self.bars)
        self.is_playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(50)

    def set_playing(self, playing: bool):
        self.is_playing = playing
        if not playing:
            self.target_bars = [0.1] * len(self.bars)
        self.update()

    def update_animation(self):
        if self.is_playing:
            self.target_bars = [random.uniform(0.15, 1.0) for _ in range(len(self.bars))]
        for i in range(len(self.bars)):
            self.bars[i] += (self.target_bars[i] - self.bars[i]) * 0.35
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bar_count = len(self.bars)
        bar_width = (w - (bar_count - 1) * 3) / bar_count

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(255, 75, 145))
        grad.setColorAt(1.0, QColor(107, 70, 255))

        for i, val in enumerate(self.bars):
            bar_h = max(3.0, val * (h - 4))
            x = i * (bar_width + 3)
            y = h - bar_h
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), 2, 2)


class MusicBarWidget(QWidget):
    """Стильный плавающий оверлей для Windows с мониторингом медиапотока"""
    def __init__(self):
        super().__init__()
        self.drag_position = QPoint()
        self.always_on_top = True
        self.demo_mode = False
        self.current_title = "Ожидание трека..."
        self.current_artist = "Запустите плеер (Spotify, Браузер, Яндекс Музыка)"
        self.current_position = 0
        self.current_duration = 180
        self.is_playing = False
        self.cover_pixmap = None
        self.session_manager = None
        self.current_session = None

        self.init_ui()
        self.init_media_manager()

        # Таймер опроса Windows Media Control
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.sync_media_state)
        self.poll_timer.start(1000)

        # Таймер прогресс-бара
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
        self.resize(460, 100)

        # Центрируем в верхней трети экрана или правом нижнем углу
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 480, screen.height() - 170)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Главный контейнер со стеклянным фоном
        self.container = QFrame(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            QFrame#container {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(22, 24, 38, 0.95),
                    stop:1 rgba(34, 37, 58, 0.92));
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 18px;
            }
        """)

        # Тень
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 6)
        self.container.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self.container)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # 1. Обложка альбома
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(62, 62)
        self.cover_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #7928CA, stop:1 #FF0080);
            border-radius: 12px;
            color: white;
            font-size: 24px;
            font-weight: bold;
        """)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("🎵")
        layout.addWidget(self.cover_label)

        # 2. Инфо о треке и прогресс-бар
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setContentsMargins(0, 4, 0, 4)

        # Название трека
        self.title_label = QLabel(self.current_title, self)
        self.title_label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 700; font-family: 'Segoe UI', sans-serif;")
        self.title_label.setMaximumWidth(210)
        info_layout.addWidget(self.title_label)

        # Исполнитель
        self.artist_label = QLabel(self.current_artist, self)
        self.artist_label.setStyleSheet("color: #A0A5BD; font-size: 11px; font-family: 'Segoe UI', sans-serif;")
        self.artist_label.setMaximumWidth(210)
        info_layout.addWidget(self.artist_label)

        # Прогресс-бар
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6B46FF, stop:1 #FF4B91);
                border-radius: 2px;
            }
        """)
        info_layout.addWidget(self.progress_bar)

        # Тайминги
        self.time_label = QLabel("0:00 / 0:00", self)
        self.time_label.setStyleSheet("color: #6C728E; font-size: 9px; font-family: monospace;")
        info_layout.addWidget(self.time_label)

        layout.addLayout(info_layout, stretch=1)

        # 3. Визуализатор
        self.visualizer = VisualizerWidget(self)
        layout.addWidget(self.visualizer)

        # 4. Кнопки управления воспроизведением
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(6)

        btn_style = """
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 15px;
                font-size: 13px;
                font-weight: bold;
                width: 30px;
                height: 30px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
                border: 1px solid rgba(255, 255, 255, 0.25);
            }
            QPushButton:pressed {
                background: #6B46FF;
            }
        """

        self.prev_btn = QPushButton("⏮", self)
        self.prev_btn.setStyleSheet(btn_style)
        self.prev_btn.setToolTip("Предыдущий трек")
        self.prev_btn.clicked.connect(self.skip_prev)
        controls_layout.addWidget(self.prev_btn)

        self.play_btn = QPushButton("▶", self)
        self.play_btn.setStyleSheet(btn_style.replace("30px", "34px"))
        self.play_btn.setToolTip("Воспроизведение / Пауза")
        self.play_btn.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self.play_btn)

        self.next_btn = QPushButton("⏭", self)
        self.next_btn.setStyleSheet(btn_style)
        self.next_btn.setToolTip("Следующий трек")
        self.next_btn.clicked.connect(self.skip_next)
        controls_layout.addWidget(self.next_btn)

        layout.addLayout(controls_layout)

        # 5. Сервисные кнопки (Демо, Закрыть, Закрепить)
        util_layout = QVBoxLayout()
        util_layout.setSpacing(4)

        util_btn_style = """
            QPushButton {
                background: transparent;
                color: #8C92AC;
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
        self.demo_btn.setToolTip("Включить демонстрационный трек")
        self.demo_btn.clicked.connect(self.toggle_demo)
        util_layout.addWidget(self.demo_btn)

        self.pin_btn = QPushButton("📌", self)
        self.pin_btn.setStyleSheet(util_btn_style)
        self.pin_btn.setToolTip("Поверх всех окон")
        self.pin_btn.clicked.connect(self.toggle_pin)
        util_layout.addWidget(self.pin_btn)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setStyleSheet(util_btn_style)
        self.close_btn.setToolTip("Закрыть виджет")
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
            except Exception as ex:
                print(f"[MusicBar] Не удалось подключиться к WinRT MediaManager: {ex}")

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
                return

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Получаем инфо о треке
            info = loop.run_until_complete(session.try_get_media_properties_async())
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()

            if info:
                title = info.title if info.title else "Без названия"
                artist = info.artist if info.artist else "Неизвестный исполнитель"
                self.title_label.setText(title)
                self.artist_label.setText(artist)

                # Проверяем обложку альбома
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
                                62, 62,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation
                            ))
                            self.cover_label.setText("")

            # Проверяем статус воспроизведения
            if playback:
                is_playing = (playback.playback_status == PlaybackStatus.PLAYING)
                self.is_playing = is_playing
                self.play_btn.setText("⏸" if is_playing else "▶")
                self.visualizer.set_playing(is_playing)

            # Проверяем таймлайн
            if timeline and timeline.end_time:
                duration_sec = timeline.end_time.total_seconds()
                pos_sec = timeline.position.total_seconds() if timeline.position else 0
                if duration_sec > 0:
                    self.current_position = int(pos_sec)
                    self.current_duration = int(duration_sec)
                    pct = int((pos_sec / duration_sec) * 100)
                    self.progress_bar.setValue(min(100, max(0, pct)))
                    self.time_label.setText(f"{self.format_time(pos_sec)} / {self.format_time(duration_sec)}")
        except Exception as e:
            # Сессия могла закрыться или смениться
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
            self.title_label.setText("Midnight City (Live)")
            self.artist_label.setText("M83 — Portfolio Demo Master")
            self.current_position = 42
            self.current_duration = 244
            self.is_playing = True
            self.play_btn.setText("⏸")
            self.visualizer.set_playing(True)
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("🌌")
            self.demo_btn.setStyleSheet("color: #FF0080; font-weight: bold; background: transparent; border: none;")
        else:
            self.demo_btn.setStyleSheet("color: #8C92AC; background: transparent; border: none;")
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
            self.title_label.setText("Cyberpunk 2077 Night Mix")
            self.artist_label.setText("Hyper — Spoiler (Synthwave)")
            self.current_position = 0
            self.current_duration = 210
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
            self.title_label.setText("Starboy (Remix)")
            self.artist_label.setText("The Weeknd feat. Daft Punk")
            self.current_position = 0
            self.current_duration = 230
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
            self.pin_btn.setStyleSheet("color: #00FFCC; font-weight: bold; background: transparent; border: none;")
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet("color: #8C92AC; background: transparent; border: none;")
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
