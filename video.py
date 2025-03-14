import sys
import os
import json
import re
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional, Set
import subprocess
import shutil
import threading
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import time
from abc import ABC, abstractmethod
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QProgressBar, QListWidget, QFrame,
                             QRadioButton, QButtonGroup, QMessageBox, QStyle)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QRunnable, QThreadPool
from PyQt6.QtGui import QIcon, QFont, QKeySequence, QShortcut, QPixmap, QCursor
import yt_dlp

# Настройка логирования
log_dir: str = "logs"
os.makedirs(log_dir, exist_ok=True)
current_date: str = datetime.now().strftime("%Y-%m-%d")
log_file: str = os.path.join(log_dir, f"video_downloader_{current_date}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(funcName)s(%(lineno)d): %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('VideoDownloader')

def setup_logging():
    log_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    log_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(funcName)s(%(lineno)d): %(message)s'
    ))
    logger.addHandler(log_handler)

# Функция для получения пути к ресурсам, корректно работающая с PyInstaller
def get_resource_path(relative_path: str) -> str:
    """
    Получает абсолютный путь к ресурсу, корректно работает как в режиме разработки,
    так и в скомпилированном PyInstaller EXE.
    """
    try:
        # PyInstaller создает временную директорию и сохраняет путь в _MEIPASS
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)
    except Exception as e:
        logger.error(f"Ошибка при определении пути ресурса {relative_path}: {e}")
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

class VideoURL:
    """Класс для работы с URL видео и определения сервиса."""
    
    # Константы с паттернами URL для разных сервисов
    URL_PATTERNS = {
        'YouTube': [
            r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$',
            r'^https?://youtu\.be/[\w-]{11}(?:\?\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/shorts/[\w-]{11}(?:\?\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/embed/[\w-]{11}(?:\?\S*)?$'
        ],
        'VK': [
            r'^https?://(?:www\.)?vk\.com/video-?\d+_\d+(?:\?\S*)?$',
            r'^https?://(?:www\.)?vkvideo\.ru/video-?\d+_\d+(?:\?\S*)?$'
        ],
        'RuTube': [
            r'^https?://(?:www\.)?rutube\.ru/video/[\w-]{32}/?(?:\?\S*)?$',
            r'^https?://(?:www\.)?rutube\.ru/play/embed/[\w-]{32}/?(?:\?\S*)?$'
        ],
        'Одноклассники': [
            r'^https?://(?:www\.)?ok\.ru/video/\d+(?:\?\S*)?$'
        ],
        'Mail.ru': [
            r'^https?://(?:www\.)?my\.mail\.ru/(?:[\w/]+/)?video/(?:[\w/]+/)\d+\.html(?:\?\S*)?$'
        ]
    }

    @classmethod
    def get_service_name(cls, url: str) -> str:
        """Определяет название видеосервиса по URL."""
        if not url:
            return 'Неизвестный сервис'
            
        for service, patterns in cls.URL_PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, url):
                    return service
                    
        # Проверка по доменам, если точное совпадение не найдено
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'YouTube'
        elif 'vk.com' in url or 'vkvideo.ru' in url:
            return 'VK'
        elif 'rutube.ru' in url:
            return 'RuTube'
        elif 'ok.ru' in url:
            return 'Одноклассники'
        elif 'mail.ru' in url:
            return 'Mail.ru'
            
        return 'Неизвестный сервис'

    @classmethod
    def is_valid(cls, url: str) -> Tuple[bool, str]:
        """
        Проверяет валидность URL для поддерживаемых видеосервисов.
        Возвращает кортеж (валидность, сообщение об ошибке).
        """
        try:
            if not url:
                raise URLValidationError("URL не может быть пустым")

            if not url.startswith(('http://', 'https://')):
                raise URLValidationError("URL должен начинаться с http:// или https://")

            for service, patterns in cls.URL_PATTERNS.items():
                for pattern in patterns:
                    if re.match(pattern, url):
                        logger.info(f"URL валиден для сервиса {service}: {url}")
                        return True, ""

            # Если URL содержит домен известного сервиса, но не соответствует паттерну
            service = cls.get_service_name(url)
            if service != 'Неизвестный сервис':
                raise URLValidationError(f"Неверный формат URL для {service}. Проверьте правильность ссылки.")

            return False, "Неподдерживаемый видеосервис или неверный формат URL"
        except URLValidationError as e:
            return False, str(e)

class DownloadMode(Enum):
    VIDEO = "video"
    AUDIO = "audio"

class ResolutionWorker(QThread):
    resolutions_found = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url: str = url

    def run(self) -> None:
        try:
            logger.info(f"Получение доступных разрешений для: {self.url}")
            ydl_opts: Dict[str, Any] = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info: Dict[str, Any] = ydl.extract_info(self.url, download=False)
                formats: List[Dict[str, Any]] = info.get('formats', [])
                # Собираем разрешения из доступных форматов
                resolutions: Set[str] = {f"{fmt['height']}p" for fmt in formats
                                          if fmt.get('height') and fmt.get('vcodec') != 'none'}
                if not resolutions:
                    resolutions = {'720p'}
                # Сортировка разрешений по убыванию
                sorted_resolutions: List[str] = sorted(list(resolutions),
                                                       key=lambda x: int(x.replace('p', '')),
                                                       reverse=True)
            logger.info(f"Найдены разрешения: {sorted_resolutions}")
            self.resolutions_found.emit(sorted_resolutions)
        except Exception as e:
            logger.exception(f"Ошибка при получении разрешений: {self.url}")
            user_friendly_error = "Не удалось получить доступные разрешения. Проверьте URL и подключение к интернету."
            self.error_occurred.emit(user_friendly_error)

# Реализация QRunnable для работы с QThreadPool
class DownloadRunnable(QRunnable):
    class Signals(QObject):
        progress = pyqtSignal(str, float)
        finished = pyqtSignal(bool, str, str)
        
    def __init__(self, url: str, mode: str, resolution: Optional[str] = None,
                 output_dir: str = 'downloads') -> None:
        super().__init__()
        self.url = url
        self.mode = mode
        self.resolution = resolution
        self.output_dir = output_dir
        self.signals = self.Signals()
        self.cancel_event = threading.Event()
        self.downloaded_filename = None
        
        os.makedirs(output_dir, exist_ok=True)
        
    def run(self) -> None:
        try:
            logger.info(f"Начало загрузки (QRunnable): {self.url}")
            if self.mode == 'video':
                success = self.download_video()
            else:
                success = self.download_audio()

            if success:
                logger.info(f"Загрузка завершена успешно: {self.url}")
                self.signals.finished.emit(True, "Загрузка завершена", self.downloaded_filename or "")
            else:
                logger.info(f"Загрузка отменена: {self.url}")
                self.signals.finished.emit(False, "Загрузка отменена", "")
        except Exception as e:
            logger.exception(f"Ошибка загрузки: {self.url}")
            error_message = self.get_user_friendly_error_message(str(e))
            self.signals.finished.emit(False, error_message, "")
            
    def get_user_friendly_error_message(self, error: str) -> str:
        """Преобразует технические сообщения об ошибках в понятные для пользователя"""
        if "HTTP Error 404" in error:
            return "Ошибка: Видео не найдено (404). Возможно, оно было удалено или является приватным."
        elif "HTTP Error 403" in error:
            return "Ошибка: Доступ запрещен (403). Видео может быть недоступно в вашем регионе."
        elif "Sign in to confirm your age" in error or "age-restricted" in error:
            return "Ошибка: Видео имеет возрастные ограничения и требует авторизации."
        elif "SSL" in error or "подключени" in error.lower() or "connect" in error.lower():
            return "Ошибка подключения. Проверьте соединение с интернетом или попробуйте позже."
        elif "copyright" in error.lower() or "copyright infringement" in error:
            return "Ошибка: Видео недоступно из-за нарушения авторских прав."
        else:
            return f"Ошибка загрузки: {error}"
            
    def download_video(self) -> bool:
        try:
            if not self.resolution:
                raise Exception("Не указано разрешение для видео")
            resolution_number: str = self.resolution.replace('p', '')
            service: str = VideoURL.get_service_name(self.url)
            logger.info(f"Загрузка видео с {service} в разрешении {resolution_number}p")

            ydl_opts: Dict[str, Any] = {
                'format': f'bestvideo[height<={resolution_number}]+bestaudio/best[height<={resolution_number}]',
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(self.output_dir, '%(title)s_%(resolution)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
                'retry_sleep': 3,
                'ignoreerrors': True,
                'no_warnings': True,
                'quiet': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.params['resolution'] = self.resolution
                ydl.download([self.url])
            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки видео")
            raise
            
    def download_audio(self) -> bool:
        try:
            ydl_opts: Dict[str, Any] = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(self.output_dir, '%(title)s_audio.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки аудио")
            raise
            
    def progress_hook(self, d: Dict[str, Any]) -> None:
        if self.cancel_event.is_set():
            raise Exception("Загрузка отменена пользователем")

        if d.get('status') == 'downloading':
            try:
                downloaded: float = d.get('downloaded_bytes', 0)
                total: float = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                if total:
                    percent: float = (downloaded / total) * 100
                    self.signals.progress.emit(f"Загрузка: {percent:.1f}%", percent)
                else:
                    # Если размер неизвестен, отправляем неопределенный прогресс
                    self.signals.progress.emit("Загрузка...", -1)
            except Exception as e:
                logger.exception("Ошибка в progress_hook")
        elif d.get('status') == 'finished':
            self.downloaded_filename = os.path.basename(d.get('filename', ''))
            self.signals.progress.emit("Обработка файла...", 100)
            
    def cancel(self) -> None:
        self.cancel_event.set()
        logger.info(f"Запрошена отмена загрузки: {self.url}")

# Функция для загрузки изображений для многократного использования
def load_image(image_name: str, size: Tuple[int, int] = (100, 100)) -> Tuple[bool, Optional[QPixmap], str]:
    """
    Загружает изображение с проверкой различных расширений.
    
    Args:
        image_name: Имя файла без расширения
        size: Размер для масштабирования (ширина, высота)
        
    Returns:
        Tuple из (успех загрузки, pixmap или None, путь к файлу)
    """
    # Изменяем порядок расширений, чтобы PNG был первым
    extensions = [".png", ".jpeg", ".jpg", ".gif", ".ico"]
    
    for ext in extensions:
        image_path = get_resource_path(f"{image_name}{ext}")
        if os.path.exists(image_path):
            try:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    # Масштабируем изображение до указанного размера
                    scaled_pixmap = pixmap.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio, 
                                             Qt.TransformationMode.SmoothTransformation)
                    logger.info(f"Изображение успешно загружено: {image_path}")
                    return True, scaled_pixmap, image_path
                else:
                    logger.warning(f"Изображение не удалось загрузить (пустой pixmap): {image_path}")
            except Exception as e:
                logger.exception(f"Ошибка при загрузке изображения {image_path}")
    
    logger.warning(f"Изображение {image_name} не найдено ни с одним из поддерживаемых расширений")
    return False, None, ""

def load_app_logo(size: Tuple[int, int] = (80, 80), for_app_icon: bool = False) -> Tuple[bool, Optional[QPixmap], str]:
    """
    Загружает логотип приложения с указанным размером.
    
    Args:
        size: Кортеж (ширина, высота) для масштабирования
        for_app_icon: Если True, загружает версию для иконки приложения
        
    Returns:
        Tuple[bool, Optional[QPixmap], str]: (успех загрузки, pixmap или None, путь к файлу)
    """
    image_path = get_resource_path("vid1.png")
    logger.info(f"Загрузка логотипа из: {image_path}")
    
    if os.path.exists(image_path):
        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(size[0], size[1], 
                                            Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
                logger.info(f"Логотип успешно загружен: {image_path}")
                return True, scaled_pixmap, image_path
            else:
                logger.warning(f"Логотип не удалось загрузить (пустой pixmap): {image_path}")
        except Exception as e:
            logger.exception(f"Ошибка при загрузке логотипа: {image_path}")
    else:
        logger.warning(f"Файл логотипа не найден: {image_path}")
    
    return False, None, ""

class VideoDownloaderError(Exception):
    """Базовое исключение для приложения"""
    pass

class URLValidationError(VideoDownloaderError):
    """Ошибка валидации URL"""
    pass

class DownloadError(VideoDownloaderError):
    """Ошибка загрузки"""
    pass

class ThemeManager:
    @staticmethod
    def get_dark_theme() -> str:
        return """
            QMainWindow { 
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QFrame { 
                background-color: #333333;
                border-radius: 10px;
                padding: 20px;
            }
            QPushButton {
                background-color: #0d47a1;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover { 
                background-color: #1565c0;
            }
        """

    @staticmethod
    def get_light_theme() -> str:
        return """
            QMainWindow { 
                background-color: rgb(208, 203, 223);
            }
            QFrame { 
                background-color: rgb(245, 242, 231);
                border-radius: 10px;
                padding: 20px;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover { 
                background-color: #1976D2;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk { background-color: #4CAF50; }
        """

class DownloadManager:
    """Класс для управления загрузками видео и аудио."""
    
    def __init__(self, output_dir: str = 'downloads'):
        self.output_dir = output_dir
        self.download_queue: List[Dict[str, Any]] = []
        self.current_download: Optional[DownloadRunnable] = None
        self.successful_downloads: List[tuple] = []
        self.failed_downloads: List[tuple] = []
        os.makedirs(output_dir, exist_ok=True)

    def add_to_queue(self, url: str, mode: str, resolution: Optional[str] = None) -> bool:
        """Добавляет новую загрузку в очередь."""
        is_valid, error_message = VideoURL.is_valid(url)
        if not is_valid:
            logger.warning(f"Некорректный URL: {url}. Причина: {error_message}")
            return False

        service: str = VideoURL.get_service_name(url)
        self.download_queue.append({
            'url': url,
            'mode': mode,
            'resolution': resolution,
            'service': service
        })
        logger.info(f"Добавлено в очередь: {url}, сервис: {service}, режим: {mode}")
        return True

    def start_downloads(self) -> None:
        """Запускает процесс загрузки."""
        if not self.download_queue:
            logger.info("Очередь загрузок пуста")
            return
        
        if self.current_download is None:
            logger.info("Запуск очереди загрузок")
            self.process_queue()

    def process_queue(self) -> None:
        """Обрабатывает следующий элемент в очереди."""
        if not self.download_queue:
            logger.info("Очередь загрузок завершена")
            return

        download = self.download_queue[0]
        logger.info(f"Начало загрузки: {download['url']}, режим: {download['mode']}")

        download_runnable = DownloadRunnable(
            download['url'],
            download['mode'],
            download['resolution'],
            self.output_dir
        )
        # Устанавливаем текущую загрузку до возврата объекта
        self.current_download = download_runnable
        logger.info("Установлена текущая загрузка")
        return download_runnable

    def cancel_current_download(self) -> None:
        """Отменяет текущую загрузку."""
        if self.current_download:
            logger.info("Отмена текущей загрузки...")
            self.current_download.cancel()

    def on_download_finished(self, success: bool, message: str, filename: str) -> None:
        """Обработчик завершения загрузки."""
        if success:
            logger.info(f"Загрузка завершена успешно: {message}")
            if self.current_download and filename:
                self.successful_downloads.append((filename, self.current_download.url))
        else:
            logger.error(f"Ошибка загрузки: {message}")
            if self.current_download:
                self.failed_downloads.append((self.current_download.url, message))

        if self.download_queue:
            self.download_queue.pop(0)

        self.current_download = None

    def clear_queue(self) -> None:
        """Очищает очередь загрузок."""
        self.download_queue.clear()
        logger.info("Очередь загрузок очищена")

    def remove_from_queue(self, index: int) -> None:
        """Удаляет элемент из очереди по индексу."""
        if 0 <= index < len(self.download_queue):
            del self.download_queue[index]
            logger.info(f"Элемент {index} удален из очереди")

    def get_download_summary(self) -> str:
        """Возвращает сводку о загрузках."""
        if not self.successful_downloads and not self.failed_downloads:
            return ""

        message = "Результаты загрузки:\n\n"
        if self.successful_downloads:
            message += "Успешно загружены:\n"
            for filename, url in self.successful_downloads:
                # Определяем правильное расширение на основе имени файла
                if '_audio' in filename:
                    # Для аудио всегда будет mp3
                    display_filename = filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                else:
                    # Для видео всегда будет mp4
                    display_filename = filename.replace('.webm', '.mp4').replace('.mkv', '.mp4')
                message += f"✓ {display_filename}\n"
        if self.failed_downloads:
            message += "\nНе удалось загрузить:\n"
            for url, error in self.failed_downloads:
                short_url = url if len(url) <= 50 else url[:50] + "..."
                message += f"✗ {short_url}\n   Причина: {error}\n"
        return message

    def cleanup_temp_files(self) -> None:
        """Очищает временные файлы в папке загрузок."""
        try:
            if os.path.exists(self.output_dir):
                for file in os.listdir(self.output_dir):
                    if file.endswith(('.part', '.ytdl')):
                        full_path = os.path.join(self.output_dir, file)
                        try:
                            os.remove(full_path)
                            logger.info(f"Удалён временный файл: {full_path}")
                        except Exception as e:
                            logger.error(f"Ошибка при удалении файла {full_path}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при очистке временных файлов: {e}")

class VideoDownloaderUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Downloader")
        self.setMinimumSize(950, 600)
        
        # Установка иконки приложения
        self.setup_app_icon()
        
        # Инициализация пула потоков
        self.thread_pool = QThreadPool()
        logger.info(f"Максимальное количество потоков: {self.thread_pool.maxThreadCount()}")
        
        central_widget: QWidget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Левая и правая панели
        left_panel: QFrame = QFrame()
        right_panel: QFrame = QFrame()
        left_panel.setFrameStyle(QFrame.Shape.StyledPanel)
        right_panel.setFrameStyle(QFrame.Shape.StyledPanel)
        left_layout = QVBoxLayout(left_panel)
        right_layout = QVBoxLayout(right_panel)

        # Заголовки
        title_label: QLabel = QLabel("Video Downloader")
        title_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #2196F3; padding: 5px; margin: 5px 0 10px 0;")

        subtitle_label: QLabel = QLabel("Скачивай видео с YouTube, VK, Rutube, Mail.ru, OK")
        subtitle_label.setFont(QFont("Arial", 12))
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setStyleSheet("color: #666666; padding: 5px; margin: 0 0 10px 0;")

        separator: QFrame = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #ddd; margin: 5px 0;")

        # Поле ввода URL и кнопка "Вставить"
        url_layout: QHBoxLayout = QHBoxLayout()
        self.url_input: QLineEdit = QLineEdit()
        self.url_input.setPlaceholderText("Вставьте URL видео...")
        paste_button: QPushButton = QPushButton("Вставить (Ctrl+V)")
        paste_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(paste_button)

        # Выбор режима загрузки
        mode_group: QButtonGroup = QButtonGroup(self)
        mode_layout: QHBoxLayout = QHBoxLayout()
        self.video_radio: QRadioButton = QRadioButton("Видео (MP4)")
        self.audio_radio: QRadioButton = QRadioButton("Аудио (MP3)")
        mode_group.addButton(self.video_radio)
        mode_group.addButton(self.audio_radio)
        mode_layout.addWidget(self.video_radio)
        mode_layout.addWidget(self.audio_radio)

        # Выбор разрешения
        self.resolution_layout: QHBoxLayout = QHBoxLayout()
        self.resolution_combo: QComboBox = QComboBox()
        refresh_button: QPushButton = QPushButton("Обновить")
        refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.resolution_layout.addWidget(QLabel("Разрешение:"))
        self.resolution_layout.addWidget(self.resolution_combo)
        self.resolution_layout.addWidget(refresh_button)

        # Прогресс загрузки
        self.progress_bar: QProgressBar = QProgressBar()
        self.status_label: QLabel = QLabel("Ожидание...")
        self.status_label.setStyleSheet("color: #666666;")

        # Кнопки управления загрузкой
        buttons_layout: QHBoxLayout = QHBoxLayout()
        add_button: QPushButton = QPushButton("Добавить в очередь (Ctrl+D)")
        add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        cancel_button: QPushButton = QPushButton("Отменить")
        cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        start_button: QPushButton = QPushButton("Загрузить все (Ctrl+S)")
        start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(start_button)

        # Кнопки управления очередью (размещаем только в правой панели)
        queue_buttons_layout: QHBoxLayout = QHBoxLayout()
        clear_queue_button: QPushButton = QPushButton("Очистить очередь")
        clear_queue_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        clear_queue_button.clicked.connect(self.clear_queue)
        remove_selected_button: QPushButton = QPushButton("Удалить выбранное")
        remove_selected_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        remove_selected_button.clicked.connect(self.remove_selected)
        queue_buttons_layout.addWidget(clear_queue_button)
        queue_buttons_layout.addWidget(remove_selected_button)

        # Очередь загрузок
        self.queue_list: QListWidget = QListWidget()
        self.queue_list.setMinimumWidth(300)
        self.queue_list.setMinimumHeight(400)
        queue_label: QLabel = QLabel("Очередь загрузок")
        queue_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))

        # Информация о контактах
        contact_layout: QVBoxLayout = QVBoxLayout()
        contact_layout.setSpacing(0)
        contact_layout.setContentsMargins(0, 0, 0, 0)

        email_label: QLabel = QLabel("maks_k77@mail.ru")
        email_label.setStyleSheet("color: #A52A2A; font-weight: bold; margin: 0px; padding: 0px;")

        donate_label: QLabel = QLabel("donate: Т-Банк   2200 7001 2147 7888")
        donate_label.setStyleSheet("color: #4169E1; font-weight: bold; margin: 0px; padding: 0px;")

        # Добавляем изображение с обработчиком события
        logo_layout = QHBoxLayout()
        self.logo_label = QLabel()
        self.logo_label.setMinimumSize(64, 64)
        
        # Загружаем логотип с помощью специальной функции для PNG
        success, pixmap, _ = load_app_logo((80, 80))
        if success:
            self.logo_label.setPixmap(pixmap)
        else:
            # Если не удалось загрузить PNG, явно проверяем другие расширения
            success, pixmap, _ = load_image("vid1", (80, 80))
            if success:
                self.logo_label.setPixmap(pixmap)
            else:
                # Если изображение не найдено, показываем текст
                self.logo_label.setText("О программе")
                self.logo_label.setStyleSheet("color: blue; text-decoration: underline;")
        
        # Устанавливаем курсор и подсказку
        self.logo_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.logo_label.setToolTip("Нажмите, чтобы увидеть информацию о программе")
        self.logo_label.mousePressEvent = self.show_about_dialog
        
        # Создаем рамку для выделения области с логотипом
        logo_frame = QFrame()
        logo_frame_layout = QVBoxLayout(logo_frame)
        logo_frame_layout.setContentsMargins(5, 5, 5, 5)  # Уменьшаем внутренние отступы
        logo_frame_layout.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignCenter)  # Выравниваем по центру
        logo_frame.setFrameShape(QFrame.Shape.StyledPanel)
        logo_frame.setStyleSheet("background-color: #f0f0f0; border-radius: 5px;")
        
        logo_layout.addWidget(logo_frame)
        
        # Нижний блок левой панели - центрирование логотипа
        bottom_layout = QVBoxLayout()
        
        # Добавляем логотип внизу и выравниваем его по центру
        logo_container = QHBoxLayout()
        logo_container.addStretch()  # Растяжка слева от логотипа
        logo_container.addLayout(logo_layout)
        logo_container.addStretch()  # Растяжка справа от логотипа
        bottom_layout.addLayout(logo_container)

        # Сборка левой панели
        left_layout.addWidget(title_label)
        left_layout.addWidget(subtitle_label)
        left_layout.addWidget(separator)
        left_layout.addLayout(url_layout)
        left_layout.addLayout(mode_layout)
        left_layout.addLayout(self.resolution_layout)
        left_layout.addWidget(self.progress_bar)
        left_layout.addWidget(self.status_label)
        left_layout.addLayout(buttons_layout)
        left_layout.addStretch()
        left_layout.addLayout(bottom_layout)  # Заменяем отдельные виджеты на bottom_layout

        # Сборка правой панели
        right_layout.addWidget(queue_label)
        right_layout.addWidget(self.queue_list)
        right_layout.addLayout(queue_buttons_layout)

        # Добавляем панели в основной layout
        main_layout.addWidget(left_panel, 2)
        main_layout.addWidget(right_panel, 1)

        # Стилизация приложения
        self.setStyleSheet(ThemeManager.get_light_theme())

        # Инициализация переменных
        self.download_manager = DownloadManager()
        self.settings: Dict[str, Any] = self.load_settings()

        # Подключение сигналов
        paste_button.clicked.connect(self.paste_url)
        add_button.clicked.connect(self.add_to_queue)
        cancel_button.clicked.connect(self.cancel_download)
        refresh_button.clicked.connect(self.update_resolutions)
        start_button.clicked.connect(self.start_downloads)
        self.video_radio.toggled.connect(self.on_mode_changed)

        # Горячие клавиши
        QShortcut(QKeySequence("Ctrl+V"), self).activated.connect(self.paste_url)
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.add_to_queue)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.start_downloads)

        # Применяем настройки из файла
        self.apply_settings()

    def setup_app_icon(self) -> None:
        """Устанавливает иконку приложения."""
        success, pixmap, image_path = load_app_logo((32, 32), True)
        if success:
            app_icon = QIcon(pixmap)
            self.setWindowIcon(app_icon)
            logger.info(f"Установлена иконка приложения из: {image_path}")
        else:
            logger.warning("Файл логотипа для иконки приложения не найден")

    def load_settings(self) -> Dict[str, Any]:
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    logger.info("Настройки успешно загружены")
                    return settings
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
        return {"download_mode": "video", "last_resolution": "720p"}

    def save_settings(self) -> None:
        try:
            settings = {
                "download_mode": "video" if self.video_radio.isChecked() else "audio",
                "last_resolution": self.resolution_combo.currentText()
            }
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(settings, f)
            logger.info("Настройки сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек: {e}")

    def apply_settings(self) -> None:
        """
        Применяет загруженные настройки (например, выбор режима загрузки и последний выбор разрешения).
        """
        mode: str = self.settings.get("download_mode", "video")
        if mode == "audio":
            self.audio_radio.setChecked(True)
        else:
            self.video_radio.setChecked(True)
        # Если режим видео и есть сохранённое разрешение, устанавливаем его (после получения доступных разрешений)
        # Здесь можно добавить дополнительную логику для установки разрешения

    def paste_url(self) -> None:
        clipboard = QApplication.clipboard()
        url: str = clipboard.text().strip()

        is_valid, error_message = VideoURL.is_valid(url)
        if not is_valid:
            logger.warning(f"Попытка вставить некорректный URL: {url}. Причина: {error_message}")
            QMessageBox.warning(self, "Ошибка", error_message)
            return

        self.url_input.setText(url)
        logger.info(f"URL вставлен из буфера обмена: {url}")

        if self.video_radio.isChecked():
            self.update_resolutions()

    def update_resolutions(self) -> None:
        """
        Получает доступные разрешения в отдельном потоке для повышения отзывчивости UI.
        """
        url: str = self.url_input.text().strip()
        if not url or not url.startswith(('http://', 'https://')):
            return

        self.resolution_combo.clear()
        self.resolution_combo.addItem("Получение разрешений...")
        self.resolution_combo.setEnabled(False)
        self.status_label.setText("Получение доступных разрешений...")
        self.status_label.setStyleSheet("color: #2196F3;")
        QApplication.processEvents()

        self.resolution_worker = ResolutionWorker(url)
        self.resolution_worker.resolutions_found.connect(self.on_resolutions_found)
        self.resolution_worker.error_occurred.connect(self.on_resolutions_error)
        self.resolution_worker.start()

    def on_resolutions_found(self, sorted_resolutions: List[str]) -> None:
        self.resolution_combo.clear()
        self.resolution_combo.addItems(sorted_resolutions)
        self.resolution_combo.setEnabled(True)
        self.status_label.setText("Разрешения обновлены")
        self.status_label.setStyleSheet("color: green;")
        # Если сохранённое разрешение присутствует в списке, устанавливаем его
        last_resolution = self.settings.get("last_resolution")
        if last_resolution in sorted_resolutions:
            index = sorted_resolutions.index(last_resolution)
            self.resolution_combo.setCurrentIndex(index)

    def on_resolutions_error(self, error_msg: str) -> None:
        self.resolution_combo.clear()
        self.resolution_combo.addItem("720p")
        self.resolution_combo.setEnabled(True)
        self.status_label.setText(f"Ошибка: {error_msg}")
        self.status_label.setStyleSheet("color: red;")

    def add_to_queue(self) -> None:
        url: str = self.url_input.text().strip()
        mode: str = "video" if self.video_radio.isChecked() else "audio"
        resolution: Optional[str] = self.resolution_combo.currentText() if mode == "video" else None

        if self.download_manager.add_to_queue(url, mode, resolution):
            self.update_queue_display()
            self.url_input.clear()
            self.save_settings()
        else:
            QMessageBox.warning(self, "Ошибка", "Некорректный URL")

    def update_queue_display(self) -> None:
        self.queue_list.clear()
        for i, item in enumerate(self.download_manager.download_queue, 1):
            mode_text = f"видео ({item['resolution']})" if item['mode'] == "video" else "аудио"
            # Проверяем, является ли текущий элемент активной загрузкой
            is_current = (
                self.download_manager.current_download is not None and
                i == 1  # Первый элемент в очереди всегда является текущей загрузкой
            )
            prefix = "⌛" if is_current else " "
            self.queue_list.addItem(
                f"{prefix} {i}. [{item.get('service', 'Неизвестный сервис')}] {item['url']} - {mode_text}"
            )

    def start_downloads(self) -> None:
        if not self.download_manager.download_queue:
            QMessageBox.information(self, "Информация", "Очередь загрузок пуста")
            return

        self.set_controls_enabled(False)
        download_runnable = self.download_manager.process_queue()
        if download_runnable:
            download_runnable.signals.progress.connect(self.update_progress)
            download_runnable.signals.finished.connect(self.on_download_finished)
            self.thread_pool.start(download_runnable)
            # Обновляем отображение очереди сразу после запуска загрузки
            self.update_queue_display()

    def update_progress(self, status: str, percent: float) -> None:
        self.status_label.setText(status)
        if percent >= 0:
            self.progress_bar.setValue(int(percent))
        else:
            # Если процент отрицательный, показываем неопределенный прогресс
            self.progress_bar.setRange(0, 0)
        # Уменьшаем частоту вызовов processEvents, чтобы не нарушать основной цикл событий
        # Вызываем только раз в 5 обновлений
        self.progress_update_counter = getattr(self, 'progress_update_counter', 0) + 1
        if self.progress_update_counter % 5 == 0:
            QApplication.processEvents()

    def on_download_finished(self, success: bool, message: str, filename: str) -> None:
        self.download_manager.on_download_finished(success, message, filename)
        self.update_queue_display()

        if not self.download_manager.download_queue:
            self.show_download_summary()
            self.set_controls_enabled(True)
        else:
            self.start_downloads()

    def show_download_summary(self) -> None:
        summary = self.download_manager.get_download_summary()
        if summary:
            self.download_manager.cleanup_temp_files()
            QMessageBox.information(self, "Загрузка завершена", summary)

    def cancel_download(self) -> None:
        self.download_manager.cancel_current_download()
        self.status_label.setText("Загрузка отменяется...")
        self.status_label.setStyleSheet("color: orange;")
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 100)

    def clear_queue(self) -> None:
        if not self.download_manager.download_queue:
            return
        reply = QMessageBox.question(
            self,
            'Подтверждение',
            'Очистить очередь загрузок?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.download_manager.clear_queue()
            self.update_queue_display()
            self.status_label.setText("Очередь очищена")

    def remove_selected(self) -> None:
        current_row = self.queue_list.currentRow()
        if current_row >= 0:
            self.download_manager.remove_from_queue(current_row)
            self.update_queue_display()
            self.status_label.setText("Элемент удален из очереди")

    def show_about_dialog(self, event) -> None:
        """Показывает диалоговое окно с информацией о программе."""
        success, _, image_path = load_app_logo((120, 120))
        
        # Создаем текст с HTML-форматированием
        if success:
            about_text = (
                f"<div style='text-align: center;'><img src='{image_path}' width='120' height='120'/></div>"
                "<h2 style='text-align: center;'>Video Downloader by MaksK v1.07</h2>"
                "<p>Приложение для скачивания видео и аудио с различных видеохостингов:</p>"
                "<ul>"
                "<li>YouTube</li>"
                "<li>VK</li>"
                "<li>RuTube</li>"
                "<li>Одноклассники</li>"
                "<li>Mail.ru</li>"
                "</ul>"
                "<p><b>Сайт программы:</b> <a href='https://maks-mk.github.io/'>https://maks-mk.github.io/</a></p>"
                "<p><b>Разработчик:</b> <a href='mailto:maks_k77@mail.ru'>maks_k77@mail.ru</a></p>"
                "<p><b>Поддержать проект:</b> Т-Банк 2200 7001 2147 7888</p>"
                "<p>© 2024-2025 Все права защищены</p>"
            )
        else:
            about_text = (
                "<div style='text-align: center;'><span style='font-size: 80px; color: red;'>!</span></div>"
                "<h2 style='text-align: center;'>Video Downloader v1.07</h2>"
                "<p>Приложение для скачивания видео и аудио с различных видеохостингов:</p>"
                "<ul>"
                "<li>YouTube</li>"
                "<li>VK</li>"
                "<li>RuTube</li>"
                "<li>Одноклассники</li>"
                "<li>Mail.ru</li>"
                "</ul>"
                "<p><b>Сайт программы:</b> <a href='https://maks-mk.github.io/'>https://maks-mk.github.io/</a></p>"
                "<p><b>Разработчик:</b> <a href='mailto:maks_k77@mail.ru'>maks_k77@mail.ru</a></p>"
                "<p><b>Поддержать проект:</b> Т-Банк 2200 7001 2147 7888</p>"
                "<p>© 2024-2025 Все права защищены</p>"
            )
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("О программе")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(about_text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        
        if not success:
            msg_box.setIcon(QMessageBox.Icon.Information)
        
        msg_box.exec()

    def set_controls_enabled(self, enabled: bool) -> None:
        """
        Включает или отключает элементы управления, чтобы предотвратить изменение очереди во время загрузки.
        """
        self.url_input.setEnabled(enabled)
        self.video_radio.setEnabled(enabled)
        self.audio_radio.setEnabled(enabled)
        self.resolution_combo.setEnabled(enabled)

    def on_mode_changed(self) -> None:
        is_video: bool = self.video_radio.isChecked()
        self.resolution_combo.setVisible(is_video)
        for i in range(self.resolution_layout.count()):
            widget = self.resolution_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(is_video)

# Проверка наличия необходимых компонентов
def check_ffmpeg() -> bool:
    """
    Проверяет наличие ffmpeg и ffprobe в системе.
    Возвращает True, если оба компонента найдены, иначе False.
    """
    ffmpeg_exists = shutil.which('ffmpeg') is not None
    ffprobe_exists = shutil.which('ffprobe') is not None
    
    logger.info(f"Проверка компонентов: ffmpeg: {ffmpeg_exists}, ffprobe: {ffprobe_exists}")
    return ffmpeg_exists and ffprobe_exists

def show_error_message(title: str, message: str) -> None:
    """
    Показывает диалоговое окно с сообщением об ошибке.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()
    sys.exit(1)

if __name__ == '__main__':
    # Проверка наличия ffmpeg и ffprobe перед запуском
    if not check_ffmpeg():
        error_message = (
            "Ошибка: Отсутствуют необходимые компоненты!\n\n"
            "Для работы программы требуются ffmpeg и ffprobe.\n\n"
            "Пожалуйста, установите ffmpeg и перезапустите программу.\n"
            "Инструкции по установке:\n"
            "- Windows: https://ffmpeg.org/download.html\n"
            "- Linux: sudo apt-get install ffmpeg\n"
            "- macOS: brew install ffmpeg"
        )
        show_error_message("Отсутствуют необходимые компоненты", error_message)
    
    app = QApplication(sys.argv)
    
    # Установка иконки для всего приложения
    success, pixmap, _ = load_app_logo((32, 32), True)
    if success:
        app_icon = QIcon(pixmap)
        app.setWindowIcon(app_icon)
        logger.info("Установлена иконка приложения для QApplication")
    
    window = VideoDownloaderUI()
    window.show()
    sys.exit(app.exec())

class DownloadQueue:
    def __init__(self):
        self.queue: List[Dict[str, Any]] = []
        self.executor = ThreadPoolExecutor(max_workers=3)
        
    async def process_queue(self):
        while self.queue:
            download = self.queue[0]
            try:
                await self.process_download(download)
            except Exception as e:
                logger.exception(f"Error processing download: {e}")
            self.queue.pop(0)
            
    async def process_download(self, download: Dict[str, Any]):
        # Асинхронная обработка загрузки
        pass

class ResolutionCache:
    def __init__(self, ttl: int = 3600):  # TTL в секундах
        self.cache: Dict[str, Tuple[List[str], float]] = {}
        self.ttl = ttl
        
    def get(self, url: str) -> Optional[List[str]]:
        if url in self.cache:
            resolutions, timestamp = self.cache[url]
            if time.time() - timestamp < self.ttl:
                return resolutions
            del self.cache[url]
        return None
        
    def set(self, url: str, resolutions: List[str]) -> None:
        self.cache[url] = (resolutions, time.time())

class VideoServicePlugin(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        pass
        
    @abstractmethod
    def get_video_info(self, url: str) -> Dict[str, Any]:
        pass
        
    @abstractmethod
    def download(self, url: str, options: Dict[str, Any]) -> bool:
        pass

class YouTubePlugin(VideoServicePlugin):
    def can_handle(self, url: str) -> bool:
        return 'youtube.com' in url or 'youtu.be' in url
    
    # Реализация остальных методов

class DownloadMetrics:
    def __init__(self):
        self.total_downloads: int = 0
        self.successful_downloads: int = 0
        self.failed_downloads: int = 0
        self.total_bytes_downloaded: int = 0
        self.average_speed: float = 0.0
        
    def update_metrics(self, success: bool, bytes_downloaded: int, speed: float) -> None:
        self.total_downloads += 1
        if success:
            self.successful_downloads += 1
        else:
            self.failed_downloads += 1
        self.total_bytes_downloaded += bytes_downloaded
        self.average_speed = (self.average_speed + speed) / 2
