import sys
import os
import json
import re
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional, Set, Union
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
import hashlib
from collections import OrderedDict

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QProgressBar, QListWidget, QFrame,
                             QRadioButton, QButtonGroup, QMessageBox, QStyle)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QRunnable, QThreadPool
from PyQt6.QtGui import QIcon, QFont, QKeySequence, QShortcut, QPixmap, QCursor
from PyQt6.QtCore import QEventLoop
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
    
    # Путь к файлу конфигурации паттернов URL
    CONFIG_FILE = "url_patterns.json"
    
    # Константы с паттернами URL для разных сервисов
    URL_PATTERNS = {
        'YouTube': [
            # Стандартные видео
            r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$',
            r'^https?://youtu\.be/[\w-]{11}(?:\?\S*)?$',
            # Шорты
            r'^https?://(?:www\.)?youtube\.com/shorts/[\w-]{11}(?:\?\S*)?$',
            # Встраиваемое видео
            r'^https?://(?:www\.)?youtube\.com/embed/[\w-]{11}(?:\?\S*)?$',
            # Плейлисты
            r'^https?://(?:www\.)?youtube\.com/playlist\?list=[\w-]+(?:&\S*)?$',
            # Каналы
            r'^https?://(?:www\.)?youtube\.com/(?:channel|c|user)/[\w-]+(?:/\S*)?$',
            # Общий более гибкий паттерн для обработки новых форматов
            r'^https?://(?:www\.)?youtube\.com/\S+[\?&]v=[\w-]{11}(?:&\S*)?$',
            # YouTube Music
            r'^https?://music\.youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$',
            # YouTube TV
            r'^https?://(?:www\.)?youtube\.com/tv#/watch/video/control\?v=[\w-]{11}$',
            # Плейлисты YouTube Music
            r'^https?://music\.youtube\.com/playlist\?list=[\w-]+(?:&\S*)?$',
            # YouTube Clips
            r'^https?://(?:www\.)?youtube\.com/clip/[\w-]+(?:\?\S*)?$'
        ],
        'VK': [
            # Стандартные видео
            r'^https?://(?:www\.)?vk\.com/video-?\d+_\d+(?:\?\S*)?$',
            r'^https?://(?:www\.)?vkvideo\.ru/video-?\d+_\d+(?:\?\S*)?$',
            # Видео в группах
            r'^https?://(?:www\.)?vk\.com/(?:video|clip)-?\d+(?:_\d+)?(?:\?\S*)?$',
            # Альбомы с видео
            r'^https?://(?:www\.)?vk\.com/videos-?\d+(?:\?\S*)?$',
            # Видео по относительному пути
            r'^https?://(?:www\.)?vk\.com/\S+$',
            # Клипы
            r'^https?://(?:www\.)?vk\.com/clips-?\d+(?:\?\S*)?$',
            # Мобильная версия
            r'^https?://(?:m\.)?vk\.com/video(?:_ext)?\.php\?.*oid=(?:-?\d+).*id=\d+.*$',
            # VK video embed
            r'^https?://(?:www\.)?vk\.com/video_ext\.php\?.*oid=(?:-?\d+).*id=\d+.*$'
        ],
        'RuTube': [
            # Стандартные видео
            r'^https?://(?:www\.)?rutube\.ru/video/[\w-]{32}/?(?:\?\S*)?$',
            r'^https?://(?:www\.)?rutube\.ru/play/embed/[\w-]{32}/?(?:\?\S*)?$',
            # Каналы
            r'^https?://(?:www\.)?rutube\.ru/channel/\d+(?:/\S*)?$',
            # Плейлисты 
            r'^https?://(?:www\.)?rutube\.ru/playlist/\d+(?:/\S*)?$',
            # Более общий паттерн для обработки новых форматов
            r'^https?://(?:www\.)?rutube\.ru/\S+/[\w-]{32}/?(?:\?\S*)?$',
            # Видео по ID
            r'^https?://(?:www\.)?rutube\.ru/video/(?:private/)?[\w-]{32}/?(?:\?\S*)?$',
            # Мобильная версия
            r'^https?://(?:m\.)?rutube\.ru/video/[\w-]{32}/?(?:\?\S*)?$',
            # Embed с параметрами
            r'^https?://(?:www\.)?rutube\.ru/play/embed/[\w-]{32}\?.*$',
            # Новые URL-адреса rutube
            r'^https?://(?:www\.)?rutube\.ru/(?:tracks|live|movies|person|metainfo)/[\w-]+/?(?:\?\S*)?$'
        ],
        'Одноклассники': [
            # Стандартные видео
            r'^https?://(?:www\.)?ok\.ru/video/\d+(?:\?\S*)?$',
            # Видео в группах
            r'^https?://(?:www\.)?ok\.ru/(?:group|profile)/\d+/\S+$',
            # Более гибкий паттерн для обработки других форматов
            r'^https?://(?:www\.)?ok\.ru/\S+/\d+(?:/\S*)?$',
            # Мобильная версия (m.ok.ru)
            r'^https?://(?:m\.)?ok\.ru/dk\?.*(?:st\.mvId|st\.discId)=\d+.*$',
            # Видео по ID и токену
            r'^https?://(?:www\.)?ok\.ru/videoembed/\d+(?:\?\S*)?$',
            # Мобильное приложение
            r'^https?://(?:www\.)?ok\.ru/live/\d+(?:\?\S*)?$',
            # Прямые трансляции
            r'^https?://(?:www\.)?ok\.ru/video/\d+/movieLayer(?:\?\S*)?$'
        ],
        'Mail.ru': [
            # Стандартные видео
            r'^https?://(?:www\.)?my\.mail\.ru/(?:[\w/]+/)?video/(?:[\w/]+/)\d+\.html(?:\?\S*)?$',
            # Новые форматы видео
            r'^https?://(?:www\.)?my\.mail\.ru/(?:[\w/]+/)?video/(?:[\w/]+/)?(?:\S+)/\d+(?:\.html)?(?:\?\S*)?$',
            # Более гибкий паттерн
            r'^https?://(?:www\.)?my\.mail\.ru/(?:[\w/]+/)?video/(?:[\w/]+/)?(?:\S+)(?:\?\S*)?$',
            # Мобильная версия
            r'^https?://(?:m\.)?my\.mail\.ru/(?:[\w/]+/)?video/(?:[\w/]+/)?(?:\d+|[\w-]+)(?:\.html)?(?:\?\S*)?$',
            # Видео в почте
            r'^https?://(?:www\.)?my\.mail\.ru/mail/[\w\.-]+/video/_myvideo/\d+\.html(?:\?\S*)?$',
            # Видео от сообществ
            r'^https?://(?:www\.)?my\.mail\.ru/community/[\w\.-]+/video/\d+\.html(?:\?\S*)?$',
            # Плейлисты
            r'^https?://(?:www\.)?my\.mail\.ru/(?:[\w/]+/)?video/playlist/\d+(?:\.html)?(?:\?\S*)?$'
        ],
        'Bilibili': [
            # Стандартные видео
            r'^https?://(?:www\.)?bilibili\.com/video/[Bb][Vv][\w-]+(?:\?\S*)?$',
            r'^https?://(?:www\.)?b23\.tv/[Bb][Vv][\w-]+(?:\?\S*)?$',
            # Короткая ссылка
            r'^https?://(?:www\.)?b23\.tv/[\w-]+(?:\?\S*)?$',
            # Пользовательские страницы
            r'^https?://(?:space|www)\.bilibili\.com/[\d]+(?:/?\?\S*)?$'
        ],
        'TikTok': [
            # Стандартные видео
            r'^https?://(?:www\.)?tiktok\.com/@[\w\.-]+/video/\d+(?:\?\S*)?$',
            # Короткие ссылки
            r'^https?://(?:vm|vt)\.tiktok\.com/[\w\.-]+/?(?:\?\S*)?$',
            # Мобильная версия
            r'^https?://(?:m\.)?tiktok\.com/v/\d+(?:\.html)?(?:\?\S*)?$',
            # Embed-версия
            r'^https?://(?:www\.)?tiktok\.com/embed/v2/\d+(?:\?\S*)?$',
            # Поисковые запросы 
            r'^https?://(?:www\.)?tiktok\.com/tag/[\w\.-]+(?:\?\S*)?$',
            # Новые форматы TikTok
            r'^https?://(?:www\.)?tiktok\.com/t/[\w\.-]+/?(?:\?\S*)?$'
        ],
        'Twitch': [
            # Стандартные клипы
            r'^https?://(?:www\.)?twitch\.tv/(?!videos/)[\w\.-]+/clip/[\w\.-]+(?:\?\S*)?$',
            # Прямые трансляции
            r'^https?://(?:www\.)?twitch\.tv/[\w\.-]+/?(?:\?\S*)?$',
            # Видео по ID
            r'^https?://(?:www\.)?twitch\.tv/videos/\d+(?:\?\S*)?$',
            # Категории
            r'^https?://(?:www\.)?twitch\.tv/directory/game/[\w\%\+\.-]+(?:\?\S*)?$',
            # Клипы по ID
            r'^https?://clips\.twitch\.tv/[\w\.-]+(?:\?\S*)?$'
        ],
        'Vimeo': [
            # Стандартные видео
            r'^https?://(?:www\.)?vimeo\.com/\d+(?:\?\S*)?$',
            # Каналы
            r'^https?://(?:www\.)?vimeo\.com/channels/[\w\.-]+(?:/\d+)?(?:\?\S*)?$',
            # Группы
            r'^https?://(?:www\.)?vimeo\.com/groups/[\w\.-]+/videos/\d+(?:\?\S*)?$',
            # Альбомы
            r'^https?://(?:www\.)?vimeo\.com/album/\d+/video/\d+(?:\?\S*)?$',
            # Обзоры
            r'^https?://(?:www\.)?vimeo\.com/review/\d+/\d+(?:\?\S*)?$',
            # Embed
            r'^https?://player\.vimeo\.com/video/\d+(?:\?\S*)?$'
        ],
        'Facebook': [
            # Стандартные видео
            r'^https?://(?:www\.|web\.|m\.)?facebook\.com/(?:watch/?\?v=|[\w\.-]+/videos/)\d+(?:\?\S*)?$',
            # Видео в постах
            r'^https?://(?:www\.|web\.|m\.)?facebook\.com/[\w\.-]+/posts/\d+(?:\?\S*)?$',
            # Видео с хэштегами
            r'^https?://(?:www\.|web\.|m\.)?facebook\.com/hashtag/[\w\.-]+(?:\?\S*)?$',
            # Короткие ссылки
            r'^https?://fb\.watch/[\w\.-]+/?(?:\?\S*)?$',
            # Рилы
            r'^https?://(?:www\.|web\.|m\.)?facebook\.com/reel/\d+(?:\?\S*)?$'
        ],
        'Instagram': [
            # Стандартные посты
            r'^https?://(?:www\.)?instagram\.com/p/[\w\.-]+/?(?:\?\S*)?$',
            # Рилы
            r'^https?://(?:www\.)?instagram\.com/reel/[\w\.-]+/?(?:\?\S*)?$',
            # Сторис
            r'^https?://(?:www\.)?instagram\.com/stories/[\w\.-]+/\d+/?(?:\?\S*)?$',
            # IGTV
            r'^https?://(?:www\.)?instagram\.com/tv/[\w\.-]+/?(?:\?\S*)?$',
            # Профили
            r'^https?://(?:www\.)?instagram\.com/[\w\.-]+/?(?:\?\S*)?$'
        ],
        'Telegram': [
            # Видео из каналов
            r'^https?://(?:www\.)?t\.me/(?!s/)[\w\.-]+/\d+(?:\?\S*)?$',
            # Публичные каналы
            r'^https?://(?:www\.)?t\.me/s/[\w\.-]+/\d+(?:\?\S*)?$',
            # Embed
            r'^https?://(?:www\.)?t\.me/embed/[\w\.-]+/\d+(?:\?\S*)?$'
        ],
        'Dailymotion': [
            # Стандартные видео
            r'^https?://(?:www\.)?dailymotion\.com/video/[\w]+(?:\?\S*)?$',
            # Плейлисты
            r'^https?://(?:www\.)?dailymotion\.com/playlist/[\w]+(?:\?\S*)?$',
            # Embed
            r'^https?://(?:www\.)?dailymotion\.com/embed/video/[\w]+(?:\?\S*)?$',
            # Пользователи
            r'^https?://(?:www\.)?dailymotion\.com/[\w]+(?:\?\S*)?$'
        ],
        'Coub': [
            # Стандартные видео
            r'^https?://(?:www\.)?coub\.com/view/[\w\.-]+(?:\?\S*)?$',
            # Embed
            r'^https?://(?:www\.)?coub\.com/embed/[\w\.-]+(?:\?\S*)?$',
            # Короткие ссылки
            r'^https?://coub\.com/[\w\.-]+/?(?:\?\S*)?$'
        ]
    }
    
    # Объединенные регулярные выражения для быстрой проверки
    _combined_patterns = {}
    _compiled_patterns = {}
    
    @classmethod
    def _init_combined_patterns(cls):
        """Инициализирует объединенные регулярные выражения для быстрой проверки."""
        if not cls._combined_patterns:
            for service, patterns in cls.URL_PATTERNS.items():
                # Объединяем все паттерны для сервиса через '|'
                combined = '|'.join(f'(?:{pattern})' for pattern in patterns)
                cls._combined_patterns[service] = combined
                try:
                    cls._compiled_patterns[service] = re.compile(combined)
                    logger.info(f"Скомпилирован объединенный паттерн для {service}")
                except re.error:
                    logger.warning(f"Ошибка при компиляции объединенного паттерна для {service}")
                    # Если не удалось скомпилировать объединенный паттерн,
                    # компилируем отдельные паттерны
                    cls._compiled_patterns[service] = [
                        (pattern, re.compile(pattern)) 
                        for pattern in patterns
                    ]
            logger.info("Объединенные регулярные выражения инициализированы")
    
    @classmethod
    def load_patterns_from_config(cls) -> bool:
        """
        Загружает паттерны URL из файла конфигурации.
        Возвращает True в случае успешной загрузки, иначе False.
        """
        try:
            if os.path.exists(cls.CONFIG_FILE):
                with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    patterns = json.load(f)
                    # Обновляем только существующие сервисы, новые не добавляем
                    for service, service_patterns in patterns.items():
                        if service in cls.URL_PATTERNS:
                            # Добавляем только новые паттерны
                            existing_patterns = set(cls.URL_PATTERNS[service])
                            for pattern in service_patterns:
                                if pattern not in existing_patterns:
                                    cls.URL_PATTERNS[service].append(pattern)
                    logger.info("Паттерны URL успешно загружены из конфигурации")
                    return True
            else:
                # Создаем файл конфигурации при первом запуске
                logger.info(f"Файл конфигурации URL-паттернов не найден, создаем новый: {cls.CONFIG_FILE}")
                cls.save_patterns_to_config()
            return False
        except Exception as e:
            logger.error(f"Ошибка загрузки паттернов URL из конфигурации: {e}")
            return False
    
    @classmethod
    def save_patterns_to_config(cls) -> bool:
        """
        Сохраняет текущие паттерны URL в файл конфигурации.
        Возвращает True в случае успешного сохранения, иначе False.
        """
        try:
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cls.URL_PATTERNS, f, ensure_ascii=False, indent=4)
            logger.info("Паттерны URL успешно сохранены в конфигурацию")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения паттернов URL в конфигурацию: {e}")
            return False
    
    @classmethod
    def register_url_pattern(cls, service: str, pattern: str) -> bool:
        """
        Регистрирует новый паттерн URL для указанного сервиса.
        Возвращает True в случае успешной регистрации, иначе False.
        """
        try:
            if service in cls.URL_PATTERNS:
                if pattern not in cls.URL_PATTERNS[service]:
                    # Проверяем валидность регулярного выражения
                    re.compile(pattern)
                    cls.URL_PATTERNS[service].append(pattern)
                    logger.info(f"Добавлен новый паттерн для {service}: {pattern}")
                    cls.save_patterns_to_config()
                    return True
            else:
                logger.warning(f"Невозможно добавить паттерн для неизвестного сервиса: {service}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при добавлении паттерна URL: {e}")
            return False

    @classmethod
    def get_service_name(cls, url: str) -> str:
        """Определяет название видеосервиса по URL."""
        if not url:
            return 'Неизвестный сервис'
        
        # Загружаем паттерны при первом запросе
        if not hasattr(cls, '_patterns_loaded'):
            cls.load_patterns_from_config()
            cls._init_combined_patterns()
            cls._patterns_loaded = True
            
        # Проверяем по объединенным паттернам для ускорения
        for service, compiled_pattern in cls._compiled_patterns.items():
            try:
                if isinstance(compiled_pattern, re.Pattern):
                    if compiled_pattern.match(url):
                        return service
                else:
                    # Если используются отдельные скомпилированные паттерны
                    for _, pattern_re in compiled_pattern:
                        if pattern_re.match(url):
                            return service
            except Exception as e:
                logger.warning(f"Ошибка при проверке URL для {service}: {e}")
                    
        # Проверка по доменам, если точное совпадение не найдено
        domain_map = {
            'youtube.com': 'YouTube',
            'youtu.be': 'YouTube',
            'music.youtube.com': 'YouTube',
            'vk.com': 'VK',
            'vkvideo.ru': 'VK',
            'rutube.ru': 'RuTube',
            'ok.ru': 'Одноклассники',
            'mail.ru': 'Mail.ru',
            'my.mail.ru': 'Mail.ru',
            'bilibili.com': 'Bilibili',
            'b23.tv': 'Bilibili',
            'tiktok.com': 'TikTok',
            'vm.tiktok.com': 'TikTok',
            'vt.tiktok.com': 'TikTok',
            'twitch.tv': 'Twitch',
            'clips.twitch.tv': 'Twitch',
            'vimeo.com': 'Vimeo',
            'player.vimeo.com': 'Vimeo',
            'facebook.com': 'Facebook',
            'fb.watch': 'Facebook',
            'instagram.com': 'Instagram',
            't.me': 'Telegram',
            'dailymotion.com': 'Dailymotion',
            'coub.com': 'Coub'
        }
        
        for domain, service in domain_map.items():
            if domain in url:
                # Если домен найден, но формат не соответствует паттернам, 
                # логируем его для возможного добавления в будущем
                cls.log_unknown_url_format(service, url)
                return service
            
        return 'Неизвестный сервис'

    @classmethod
    def log_unknown_url_format(cls, service: str, url: str) -> None:
        """
        Логирует неизвестный формат URL для возможного обновления паттернов.
        """
        try:
            log_file = f"unknown_{service.lower()}_urls.log"
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"{datetime.now()} - {url}\n")
            logger.warning(f"Обнаружен нераспознанный формат URL для {service}: {url}")
        except Exception as e:
            logger.error(f"Ошибка при логировании неизвестного формата URL: {e}")

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
                # Пытаемся исправить URL автоматически
                if '://' not in url:
                    fixed_url = f"https://{url}"
                    logger.info(f"Автоматическое исправление URL: {url} -> {fixed_url}")
                    return cls.is_valid(fixed_url)
                else:
                    raise URLValidationError("URL должен начинаться с http:// или https://")

            # Инициализируем объединенные паттерны при необходимости
            if not hasattr(cls, '_patterns_loaded'):
                cls.load_patterns_from_config()
                cls._init_combined_patterns()
                cls._patterns_loaded = True
                
            # Проверяем по объединенным паттернам для ускорения
            for service, compiled_pattern in cls._compiled_patterns.items():
                try:
                    if isinstance(compiled_pattern, re.Pattern):
                        if compiled_pattern.match(url):
                            logger.info(f"URL валиден для сервиса {service}: {url}")
                            return True, ""
                    else:
                        # Если используются отдельные скомпилированные паттерны
                        for pattern, pattern_re in compiled_pattern:
                            if pattern_re.match(url):
                                logger.info(f"URL валиден для сервиса {service}: {url}")
                                return True, ""
                except Exception as e:
                    logger.warning(f"Ошибка при проверке URL для {service}: {e}")

            # Если URL содержит домен известного сервиса, но не соответствует паттерну
            service = cls.get_service_name(url)
            if service != 'Неизвестный сервис':
                raise URLValidationError(
                    f"Неверный формат URL для {service}. Проверьте правильность ссылки или сообщите разработчику о новом формате."
                )

            return False, "Неподдерживаемый видеосервис или неверный формат URL"
        except URLValidationError as e:
            return False, str(e)
        except Exception as e:
            logger.exception(f"Неожиданная ошибка при проверке URL: {url}")
            return False, f"Ошибка при проверке URL: {str(e)}"

    @staticmethod
    def test_url(url: str) -> Dict[str, Any]:
        """
        Тестирует URL и возвращает подробную информацию о нем.
        Полезно для диагностики и отладки.
        """
        result = {
            "url": url,
            "is_valid": False,
            "error_message": "",
            "service": "Неизвестный сервис",
            "matched_pattern": None,
            "suggested_pattern": None
        }
        
        try:
            if not url:
                result["error_message"] = "URL не может быть пустым"
                return result
                
            if not url.startswith(('http://', 'https://')):
                result["error_message"] = "URL должен начинаться с http:// или https://"
                return result
                
            service = VideoURL.get_service_name(url)
            result["service"] = service
            
            # Проверяем соответствие паттернам
            for pattern in VideoURL.URL_PATTERNS.get(service, []):
                try:
                    if re.match(pattern, url):
                        result["is_valid"] = True
                        result["matched_pattern"] = pattern
                        break
                except re.error:
                    continue
            
            # Если не соответствует, пытаемся предложить паттерн
            if not result["is_valid"] and service != "Неизвестный сервис":
                # Создаем упрощенный паттерн на основе URL
                domain_part = url.split('//')[1].split('/')[0]
                path_parts = url.split(domain_part)[1]
                suggested_pattern = f"^https?://(?:www\\.)?{domain_part.replace('.', '\\.')}\\S*$"
                result["suggested_pattern"] = suggested_pattern
                result["error_message"] = f"URL не соответствует известным паттернам для {service}"
            
            if not result["is_valid"] and not result["error_message"]:
                result["error_message"] = "Неподдерживаемый видеосервис или неверный формат URL"
                
        except Exception as e:
            result["error_message"] = f"Ошибка при тестировании URL: {str(e)}"
            
        return result

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
            
            # Создаем новый event loop для асинхронных операций
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Получаем разрешения асинхронно
            resolutions = loop.run_until_complete(
                video_info_fetcher.get_video_resolutions(self.url)
            )
            
            # Закрываем loop
            loop.close()
            
            self.resolutions_found.emit(resolutions)
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
                    # Для аудио всегда будет mp3 (FFmpeg конвертирует в mp3)
                    # Заменяем любое расширение на .mp3
                    base_name = os.path.splitext(filename)[0]
                    display_filename = f"{base_name}.mp3"
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

    def reset_download_history(self) -> None:
        """Сбрасывает историю загрузок."""
        self.successful_downloads.clear()
        self.failed_downloads.clear()
        logger.info("История загрузок сброшена")

class VideoDownloaderUI(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video Downloader")
        self.setMinimumSize(970, 600)
        
        # Загрузка паттернов URL и инициализация кэша
        VideoURL.load_patterns_from_config()
        VideoURL._init_combined_patterns()
        video_info_cache.load_from_file()
        
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

        subtitle_label: QLabel = QLabel("Скачивай видео с YouTube, VK, TikTok, Instagram и других сервисов")
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
        self.start_button: QPushButton = QPushButton("Загрузить все (Ctrl+S)")
        self.start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(self.start_button)

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
        self.start_button.clicked.connect(self.start_downloads)
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
            
            # Если это неизвестный формат известного сервиса, предложим сообщить о нем
            test_info = VideoURL.test_url(url)
            if test_info["service"] != "Неизвестный сервис" and test_info["suggested_pattern"]:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Неизвестный формат URL")
                msg.setText(f"Обнаружен неизвестный формат URL для сервиса {test_info['service']}.")
                msg.setInformativeText("Хотите попробовать использовать этот URL несмотря на ошибку?\n\n"
                                       "URL будет записан в лог для возможного добавления в будущие версии.")
                msg.setDetailedText(f"URL: {url}\n"
                                   f"Сервис: {test_info['service']}\n"
                                   f"Предлагаемый паттерн: {test_info['suggested_pattern']}")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setDefaultButton(QMessageBox.StandardButton.No)
                
                if msg.exec() == QMessageBox.StandardButton.Yes:
                    # Принудительно принимаем URL и продолжаем
                    self.url_input.setText(url)
                    logger.info(f"Пользователь выбрал продолжить с неподдерживаемым URL: {url}")
                    
                    # Логируем для будущего анализа
                    VideoURL.log_unknown_url_format(test_info["service"], url)
                    
                    if self.video_radio.isChecked():
                        self.update_resolutions()
                    
                    return
            
            QMessageBox.warning(self, "Ошибка", error_message)
            return

        self.url_input.setText(url)
        logger.info(f"URL вставлен из буфера обмена: {url}")

        if self.video_radio.isChecked():
            self.update_resolutions()

    def update_resolutions(self) -> None:
        """
        Получает доступные разрешения в отдельном потоке для повышения отзывчивости UI.
        Использует кэш, если информация уже была запрошена ранее.
        """
        url: str = self.url_input.text().strip()
        if not url or not url.startswith(('http://', 'https://')):
            return

        # Проверяем, есть ли информация в кэше
        cached_info = video_info_cache.get(url)
        if cached_info and 'formats' in cached_info:
            # Извлекаем разрешения из кэша
            formats = cached_info.get('formats', [])
            resolutions = {f"{fmt['height']}p" for fmt in formats
                          if fmt.get('height') and fmt.get('vcodec') != 'none'}
            
            if not resolutions:
                resolutions = {'720p'}
                
            # Сортировка разрешений по убыванию
            sorted_resolutions = sorted(list(resolutions),
                                       key=lambda x: int(x.replace('p', '')),
                                       reverse=True)
            
            # Обновляем UI
            self.resolution_combo.clear()
            self.resolution_combo.addItems(sorted_resolutions)
            self.resolution_combo.setEnabled(True)
            self.status_label.setText("Разрешения получены из кэша")
            self.status_label.setStyleSheet("color: green;")
            
            # Если сохранённое разрешение присутствует в списке, устанавливаем его
            last_resolution = self.settings.get("last_resolution")
            if last_resolution in sorted_resolutions:
                index = sorted_resolutions.index(last_resolution)
                self.resolution_combo.setCurrentIndex(index)
                
            return

        # Если нет в кэше, показываем индикатор загрузки
        self.resolution_combo.clear()
        self.resolution_combo.addItem("Получение разрешений...")
        self.resolution_combo.setEnabled(False)
        self.status_label.setText("Получение доступных разрешений...")
        self.status_label.setStyleSheet("color: #2196F3;")
        QApplication.processEvents()

        # Запускаем асинхронное получение разрешений
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
        self.start_button.setEnabled(False)  # Дополнительно деактивируем кнопку "Загрузить все"
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
            self.start_button.setEnabled(True)  # Включаем кнопку "Загрузить все"
            self.reset_ui_after_downloads()  # Сбрасываем UI после загрузок
        else:
            self.start_downloads()

    def show_download_summary(self) -> None:
        summary = self.download_manager.get_download_summary()
        if summary:
            self.download_manager.cleanup_temp_files()
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Загрузка завершена")
            msg_box.setText(summary)
            
            # Добавляем кнопку для сброса истории загрузок
            clear_history_btn = QPushButton("Очистить историю")
            clear_history_btn.clicked.connect(self.clear_download_history)
            
            msg_box.addButton(QMessageBox.StandardButton.Ok)
            msg_box.addButton(clear_history_btn, QMessageBox.ButtonRole.ActionRole)
            
            msg_box.exec()

    def reset_ui_after_downloads(self) -> None:
        """Сбрасывает UI после завершения загрузок."""
        # Очищаем поле URL
        self.url_input.clear()
        
        # Сбрасываем прогресс
        self.progress_bar.setValue(0)
        
        # Обновляем статус
        self.status_label.setText("Загрузки завершены. Готов к новым задачам.")
        self.status_label.setStyleSheet("color: green;")
        
        # Обновляем очередь загрузок
        self.update_queue_display()
        
        logger.info("UI сброшен после загрузок")

    def clear_download_history(self) -> None:
        """Очищает историю загрузок."""
        self.download_manager.reset_download_history()
        QMessageBox.information(self, "История очищена", 
                             "История загрузок успешно очищена.")

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
                "<h2 style='text-align: center;'>Video Downloader by MaksK v1.08</h2>"
                "<p>Приложение для скачивания видео и аудио с различных видеохостингов:</p>"
                "<ul>"
                "<li>YouTube</li>"
                "<li>VK</li>"
                "<li>RuTube</li>"
                "<li>Одноклассники</li>"
                "<li>Mail.ru</li>"
                "<li>TikTok</li>"
                "<li>Instagram/Facebook</li>"
                "<li>Twitch</li>"
                "<li>Vimeo</li>"
                "<li>Telegram</li>"
                "<li>Dailymotion</li>"
                "<li>Coub</li>"
                "<li>Bilibili</li>"
                "</ul>"
                "<p><b>Сайт программы:</b> <a href='https://maks-mk.github.io/'>https://maks-mk.github.io/</a></p>"
                "<p><b>Разработчик:</b> <a href='mailto:maks_k77@mail.ru'>maks_k77@mail.ru</a></p>"
                "<p><b>Поддержать проект:</b> Т-Банк 2200 7001 2147 7888</p>"
                "<p>© 2024-2025 Все права защищены</p>"
            )
        else:
            about_text = (
                "<div style='text-align: center;'><span style='font-size: 80px; color: red;'>!</span></div>"
                "<h2 style='text-align: center;'>Video Downloader v1.08</h2>"
                "<p>Приложение для скачивания видео и аудио с различных видеохостингов:</p>"
                "<ul>"
                "<li>YouTube</li>"
                "<li>VK</li>"
                "<li>RuTube</li>"
                "<li>Одноклассники</li>"
                "<li>Mail.ru</li>"
                "<li>TikTok</li>"
                "<li>Instagram/Facebook</li>"
                "<li>Twitch</li>"
                "<li>Vimeo</li>"
                "<li>Telegram</li>"
                "<li>Dailymotion</li>"
                "<li>Coub</li>"
                "<li>Bilibili</li>"
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
        
        # Добавляем кнопку для отправки сообщения о неизвестных форматах URL
        report_btn = QPushButton("Сообщить о новом формате URL")
        report_btn.clicked.connect(self.show_url_report_dialog)
        
        # Добавляем кнопку для очистки кэша
        clear_cache_btn = QPushButton("Очистить кэш видео")
        clear_cache_btn.clicked.connect(self.clear_cache)
        
        msg_box.addButton(QMessageBox.StandardButton.Ok)
        msg_box.addButton(report_btn, QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton(clear_cache_btn, QMessageBox.ButtonRole.ActionRole)
        
        if not success:
            msg_box.setIcon(QMessageBox.Icon.Information)
        
        msg_box.exec()
        
    def show_url_report_dialog(self) -> None:
        """Показывает диалог для отправки сообщения о неизвестном формате URL."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Сообщить о новом формате URL")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("Если вы обнаружили URL видео, который не распознается программой, "
                      "вы можете отправить его разработчику для добавления поддержки.")
                      
        # Проверяем наличие логов с неизвестными URL
        unknown_logs = []
        for service in VideoURL.URL_PATTERNS.keys():
            log_file = f"unknown_{service.lower()}_urls.log"
            if os.path.exists(log_file):
                unknown_logs.append(log_file)
                
        if unknown_logs:
            log_text = "Найдены записи о неизвестных форматах URL:\n\n"
            for log_file in unknown_logs:
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        urls = f.readlines()
                        if urls:
                            log_text += f"{log_file}: {len(urls)} записей\n"
                except Exception as e:
                    logger.error(f"Ошибка при чтении лога неизвестных URL: {e}")
            
            dialog.setInformativeText(log_text + "\n\nХотите отправить эти данные разработчику?")
            dialog.setDetailedText("Нажмите 'Отправить', чтобы скопировать логи в буфер обмена и открыть "
                                  "почтовый клиент. Вы можете вставить данные в письмо и отправить его разработчику.")
                                  
            send_btn = dialog.addButton("Отправить", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            
            if dialog.exec() == 0:  # Нажата кнопка "Отправить"
                # Подготавливаем текст для отправки
                email_text = "Здравствуйте!\n\nЯ обнаружил следующие неподдерживаемые URL в Video Downloader:\n\n"
                
                for log_file in unknown_logs:
                    try:
                        with open(log_file, 'r', encoding='utf-8') as f:
                            urls = f.readlines()
                            if urls:
                                email_text += f"=== {log_file} ===\n"
                                for url in urls[-10:]:  # Берем только последние 10 записей
                                    email_text += url
                                email_text += "\n"
                    except Exception as e:
                        logger.error(f"Ошибка при чтении лога неизвестных URL: {e}")
                
                # Копируем в буфер обмена
                clipboard = QApplication.clipboard()
                clipboard.setText(email_text)
                
                # Пытаемся открыть почтовый клиент
                try:
                    import webbrowser
                    webbrowser.open("mailto:maks_k77@mail.ru?subject=Video%20Downloader%20-%20New%20URL%20Format")
                    QMessageBox.information(self, "Отправка отчета", 
                                          "Текст отчета скопирован в буфер обмена. Вставьте его в письмо.")
                except Exception as e:
                    logger.error(f"Ошибка при открытии почтового клиента: {e}")
                    QMessageBox.information(self, "Отправка отчета", 
                                          "Текст отчета скопирован в буфер обмена. Отправьте его на адрес: maks_k77@mail.ru")
        else:
            dialog.setInformativeText("Не найдено записей о неизвестных форматах URL.\n\n"
                                      "Если вы хотите сообщить о новом формате, скопируйте URL и отправьте его "
                                      "разработчику на адрес: maks_k77@mail.ru")
            dialog.addButton(QMessageBox.StandardButton.Ok)
            dialog.exec()

    def set_controls_enabled(self, enabled: bool) -> None:
        """
        Включает или отключает элементы управления, чтобы предотвратить изменение очереди во время загрузки.
        """
        self.url_input.setEnabled(enabled)
        self.video_radio.setEnabled(enabled)
        self.audio_radio.setEnabled(enabled)
        self.resolution_combo.setEnabled(enabled)
        # Кнопка "Загрузить все" управляется отдельно для более точного контроля

    def on_mode_changed(self) -> None:
        is_video: bool = self.video_radio.isChecked()
        self.resolution_combo.setVisible(is_video)
        for i in range(self.resolution_layout.count()):
            widget = self.resolution_layout.itemAt(i).widget()
            if widget:
                widget.setVisible(is_video)

    def closeEvent(self, event):
        """Обработчик закрытия приложения."""
        # Сохраняем кэш при выходе
        video_info_cache.save_to_file()
        event.accept()

    def clear_cache(self) -> None:
        """Очищает кэш информации о видео."""
        video_info_cache.clear()
        video_info_cache.save_to_file()
        QMessageBox.information(self, "Кэш очищен", 
                             "Кэш информации о видео успешно очищен.")

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

# Класс для кэширования информации о видео
class VideoInfoCache:
    """Класс для кэширования информации о видео."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        
    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """Получает информацию о видео из кэша."""
        key = self._get_key(url)
        if key in self.cache:
            # Перемещаем элемент в конец OrderedDict, чтобы сохранить LRU-порядок
            value = self.cache.pop(key)
            self.cache[key] = value
            logger.info(f"Информация о видео получена из кэша: {url}")
            return value
        return None
        
    def set(self, url: str, info: Dict[str, Any]) -> None:
        """Добавляет информацию о видео в кэш."""
        key = self._get_key(url)
        
        # Если кэш полон, удаляем самый старый элемент (первый в OrderedDict)
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)
            
        self.cache[key] = info
        logger.info(f"Информация о видео добавлена в кэш: {url}")
        
    def clear(self) -> None:
        """Очищает кэш."""
        self.cache.clear()
        logger.info("Кэш информации о видео очищен")
        
    def _get_key(self, url: str) -> str:
        """Генерирует ключ для кэша на основе URL."""
        return hashlib.md5(url.encode()).hexdigest()
        
    def save_to_file(self, filename: str = 'video_cache.json') -> bool:
        """Сохраняет кэш в файл."""
        try:
            # Преобразуем OrderedDict в обычный словарь для сериализации
            cache_data = {k: v for k, v in self.cache.items()}
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f)
            logger.info(f"Кэш успешно сохранен в файл: {filename}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении кэша в файл: {e}")
            return False
            
    def load_from_file(self, filename: str = 'video_cache.json') -> bool:
        """Загружает кэш из файла."""
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    # Преобразуем обычный словарь в OrderedDict
                    self.cache = OrderedDict(cache_data)
                logger.info(f"Кэш успешно загружен из файла: {filename}")
                return True
            else:
                logger.info(f"Файл кэша не найден: {filename}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при загрузке кэша из файла: {e}")
            return False

# Создаем глобальный экземпляр кэша
video_info_cache = VideoInfoCache()

# Асинхронный класс для получения информации о видео
class AsyncVideoInfoFetcher:
    """Класс для асинхронного получения информации о видео."""
    
    def __init__(self):
        self.loop = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        
    async def get_video_info(self, url: str) -> Dict[str, Any]:
        """Асинхронно получает информацию о видео."""
        # Проверяем, есть ли информация в кэше
        cached_info = video_info_cache.get(url)
        if cached_info:
            return cached_info
            
        # Если нет в кэше, получаем асинхронно
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(
            self.executor,
            self._extract_info,
            url
        )
        
        # Сохраняем в кэш
        if info:
            video_info_cache.set(url, info)
            
        return info
        
    def _extract_info(self, url: str) -> Dict[str, Any]:
        """Извлекает информацию о видео с использованием yt-dlp."""
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.exception(f"Ошибка при получении информации о видео: {url}")
            return None
            
    async def get_video_resolutions(self, url: str) -> List[str]:
        """Асинхронно получает доступные разрешения видео."""
        try:
            info = await self.get_video_info(url)
            if not info:
                return ['720p']  # Возвращаем значение по умолчанию
                
            formats = info.get('formats', [])
            # Собираем разрешения из доступных форматов
            resolutions = {f"{fmt['height']}p" for fmt in formats
                            if fmt.get('height') and fmt.get('vcodec') != 'none'}
            
            if not resolutions:
                return ['720p']
                
            # Сортировка разрешений по убыванию
            sorted_resolutions = sorted(list(resolutions),
                                       key=lambda x: int(x.replace('p', '')),
                                       reverse=True)
            
            logger.info(f"Найдены разрешения: {sorted_resolutions}")
            return sorted_resolutions
        except Exception as e:
            logger.exception(f"Ошибка при получении разрешений: {url}")
            return ['720p']

# Создаем глобальный экземпляр асинхронного получателя информации
video_info_fetcher = AsyncVideoInfoFetcher()

# Обновляем класс ResolutionWorker для использования асинхронного получения разрешений
class ResolutionWorker(QThread):
    resolutions_found = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url: str = url

    def run(self) -> None:
        try:
            logger.info(f"Получение доступных разрешений для: {self.url}")
            
            # Создаем новый event loop для асинхронных операций
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Получаем разрешения асинхронно
            resolutions = loop.run_until_complete(
                video_info_fetcher.get_video_resolutions(self.url)
            )
            
            # Закрываем loop
            loop.close()
            
            self.resolutions_found.emit(resolutions)
        except Exception as e:
            logger.exception(f"Ошибка при получении разрешений: {self.url}")
            user_friendly_error = "Не удалось получить доступные разрешения. Проверьте URL и подключение к интернету."
            self.error_occurred.emit(user_friendly_error)

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
    
    # Загружаем кэш при старте
    video_info_cache.load_from_file()
    
    app = QApplication(sys.argv)
    
    # Установка иконки для всего приложения
    success, pixmap, _ = load_app_logo((32, 32), True)
    if success:
        app_icon = QIcon(pixmap)
        app.setWindowIcon(app_icon)
        logger.info("Установлена иконка приложения для QApplication")
    
    window = VideoDownloaderUI()
    window.show()
    
    # Сохраняем кэш при выходе
    app.aboutToQuit.connect(lambda: video_info_cache.save_to_file())
    
    sys.exit(app.exec())
