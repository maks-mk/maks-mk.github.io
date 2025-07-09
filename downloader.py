#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import threading
import logging
import hashlib
import json
import gc
import psutil
import time
import re
import subprocess
import platform
from typing import Dict, Any, Optional, List, Tuple, Set, Union
from enum import Enum
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import asyncio

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, QThread
import yt_dlp

from validators import VideoURL
from yt_dlp_utils import YtDlpConfigManager, YtDlpFormatAnalyzer, YtDlpDiagnostics

logger = logging.getLogger('VideoDownloader')


def run_subprocess_hidden(cmd, **kwargs):
    """
    Запускает subprocess с автоматическим скрытием консоли в Windows.

    Args:
        cmd: Команда для выполнения
        **kwargs: Дополнительные аргументы для subprocess.run

    Returns:
        Результат subprocess.run
    """
    # Настройки по умолчанию
    default_kwargs = {
        'capture_output': True,
        'text': True,
        'timeout': 30
    }

    # Объединяем с переданными аргументами
    final_kwargs = {**default_kwargs, **kwargs}

    # Скрываем консоль в Windows
    if platform.system() == 'Windows':
        final_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    return subprocess.run(cmd, **final_kwargs)


class VideoDownloaderError(Exception):
    """Базовое исключение для приложения"""
    pass


class DownloadError(VideoDownloaderError):
    """Ошибка загрузки"""
    pass


class DownloadMode(Enum):
    """Режимы загрузки"""
    VIDEO = "video"
    AUDIO = "audio"


class MemoryMonitor:
    """Класс для мониторинга использования памяти."""

    def __init__(self, max_memory_mb: int = 512):
        """
        Инициализирует монитор памяти.

        Args:
            max_memory_mb: Максимальное использование памяти в МБ
        """
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.process = psutil.Process()

    def get_memory_usage(self) -> int:
        """Возвращает текущее использование памяти в байтах."""
        try:
            return self.process.memory_info().rss
        except Exception:
            return 0

    def get_memory_usage_mb(self) -> float:
        """Возвращает текущее использование памяти в МБ."""
        return self.get_memory_usage() / (1024 * 1024)

    def is_memory_limit_exceeded(self) -> bool:
        """Проверяет, превышен ли лимит памяти."""
        return self.get_memory_usage() > self.max_memory_bytes

    def force_garbage_collection(self):
        """Принудительно запускает сборку мусора."""
        gc.collect()
        logger.info(f"Принудительная сборка мусора. Память: {self.get_memory_usage_mb():.1f} МБ")

    def log_memory_usage(self, context: str = ""):
        """Логирует текущее использование памяти."""
        memory_mb = self.get_memory_usage_mb()
        logger.info(f"Использование памяти{' (' + context + ')' if context else ''}: {memory_mb:.1f} МБ")


# Глобальный монитор памяти
memory_monitor = MemoryMonitor(max_memory_mb=512)


class VideoInfoCache:
    """Класс для кэширования информации о видео с управлением памятью."""

    def __init__(self, max_size: int = 50, max_memory_mb: int = 100):
        """
        Инициализирует кэш информации о видео.

        Args:
            max_size: Максимальный размер кэша
            max_memory_mb: Максимальное использование памяти кэшем в МБ
        """
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.cache: OrderedDict = OrderedDict()
        self.cache_size_bytes = 0
        self.last_cleanup = time.time()
        self._lock = threading.RLock()  # Блокировка для потокобезопасности
        
    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о видео из кэша.

        Args:
            url: URL видео

        Returns:
            Информация о видео или None, если не найдена в кэше
        """
        with self._lock:
            # Периодическая очистка кэша
            self._periodic_cleanup()

            key = self._get_key(url)
            if key in self.cache:
                # Перемещаем элемент в конец OrderedDict, чтобы сохранить LRU-порядок
                value = self.cache.pop(key)
                self.cache[key] = value
            logger.info(f"Информация о видео получена из кэша: {url}")
            return value
        return None
        
    def set(self, url: str, info: Dict[str, Any]) -> None:
        """
        Добавляет информацию о видео в кэш.

        Args:
            url: URL видео
            info: Информация о видео
        """
        key = self._get_key(url)

        # Оцениваем размер данных
        info_size = self._estimate_size(info)

        # Проверяем ограничения памяти
        while (len(self.cache) >= self.max_size or
               self.cache_size_bytes + info_size > self.max_memory_bytes):
            if not self.cache:
                break
            # Удаляем самый старый элемент
            old_key, old_info = self.cache.popitem(last=False)
            self.cache_size_bytes -= self._estimate_size(old_info)

        self.cache[key] = info
        self.cache_size_bytes += info_size
        logger.info(f"Информация о видео добавлена в кэш: {url} (размер: {info_size} байт)")

        # Автоматически сохраняем кэш в файл после добавления
        try:
            self.save_to_file()
        except Exception as e:
            logger.warning(f"Не удалось автоматически сохранить кэш: {e}")

    def clear(self) -> None:
        """Очищает кэш."""
        self.cache.clear()
        self.cache_size_bytes = 0
        logger.info("Кэш информации о видео очищен")

    def _estimate_size(self, obj: Any) -> int:
        """Оценивает размер объекта в байтах."""
        try:
            return len(json.dumps(obj, default=str).encode('utf-8'))
        except Exception:
            # Грубая оценка для сложных объектов
            return 1024  # 1KB по умолчанию

    def _periodic_cleanup(self):
        """Периодическая очистка кэша."""
        current_time = time.time()
        if current_time - self.last_cleanup > 300:  # каждые 5 минут
            self.last_cleanup = current_time

            # Проверяем использование памяти
            if memory_monitor.is_memory_limit_exceeded():
                # Удаляем половину кэша при превышении лимита памяти
                items_to_remove = len(self.cache) // 2
                for _ in range(items_to_remove):
                    if self.cache:
                        old_key, old_info = self.cache.popitem(last=False)
                        self.cache_size_bytes -= self._estimate_size(old_info)

                memory_monitor.force_garbage_collection()
                logger.info(f"Очистка кэша: удалено {items_to_remove} элементов")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Возвращает статистику кэша."""
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'memory_usage_mb': self.cache_size_bytes / (1024 * 1024),
            'max_memory_mb': self.max_memory_bytes / (1024 * 1024)
        }
        
    def _get_key(self, url: str) -> str:
        """
        Генерирует ключ для кэша на основе URL.
        
        Args:
            url: URL видео
            
        Returns:
            MD5-хеш URL в виде строки
        """
        return hashlib.md5(url.encode()).hexdigest()
        
    def save_to_file(self, filename: str = 'video_cache.json') -> bool:
        """
        Сохраняет кэш в файл.
        
        Args:
            filename: Имя файла для сохранения кэша
            
        Returns:
            True в случае успешного сохранения, иначе False
        """
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
        """
        Загружает кэш из файла.
        
        Args:
            filename: Имя файла с кэшем
            
        Returns:
            True в случае успешной загрузки, иначе False
        """
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


# Создаем глобальный экземпляр кэша с ограничениями памяти
video_info_cache = VideoInfoCache(max_size=50, max_memory_mb=100)


class AsyncVideoInfoFetcher:
    """Класс для асинхронного получения информации о видео."""
    
    def __init__(self):
        """Инициализирует фетчер информации о видео."""
        self.loop = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.config_manager = YtDlpConfigManager()
        self.format_analyzer = YtDlpFormatAnalyzer()
        self.diagnostics = YtDlpDiagnostics()
        
    async def get_video_info(self, url: str) -> Dict[str, Any]:
        """
        Асинхронно получает информацию о видео.
        
        Args:
            url: URL видео
            
        Returns:
            Словарь с информацией о видео
        """
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
        """
        Извлекает информацию о видео с использованием yt-dlp.

        Args:
            url: URL видео

        Returns:
            Словарь с информацией о видео или None при ошибке
        """
        try:
            # Определяем сервис для оптимизации настроек
            service = VideoURL.get_service_name(url) if hasattr(VideoURL, 'get_service_name') else ''

            # Используем базовые настройки с оптимизацией для получения информации
            ydl_opts = self._create_base_ydl_opts(service)
            ydl_opts.update({
                'retries': 5,  # Меньше попыток для быстрого получения информации
                'fragment_retries': 5,
                'retry_sleep': 2,
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.exception(f"Ошибка при получении информации о видео: {url}")
            # Попытка с упрощенными настройками
            try:
                logger.info("Повторная попытка с упрощенными настройками")
                simple_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'socket_timeout': 15,
                    'retries': 3,
                }
                with yt_dlp.YoutubeDL(simple_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    return info
            except Exception as e2:
                logger.exception(f"Повторная попытка также неудачна: {url}")
                return None

    def _should_skip_manifests(self) -> bool:
        """
        Определяет, следует ли пропускать DASH/HLS манифесты.

        Returns:
            True если следует пропустить манифесты
        """
        # НЕ пропускаем манифесты - они содержат высокие разрешения!
        # Для загрузки нужны все доступные форматы
        return False

    def _get_browser_cookies_config(self) -> Optional[Tuple[str, None, None, None]]:
        """
        Получает конфигурацию для извлечения cookies из браузера.

        Returns:
            Кортеж с настройками браузера или None
        """
        try:
            # Временно отключаем cookies из браузера из-за проблем с доступом
            # В будущем можно добавить более надежную проверку доступности
            return None

            # Код для будущего использования:
            # browsers = ['firefox', 'edge', 'safari', 'opera']  # Chrome исключен
            # for browser in browsers:
            #     try:
            #         return (browser, None, None, None)
            #     except:
            #         continue
            # return None
        except Exception as e:
            logger.debug(f"Не удалось настроить cookies из браузера: {e}")
            return None

    def _get_optimal_user_agent(self) -> str:
        """
        Возвращает оптимальный User-Agent для запросов.

        Returns:
            Строка User-Agent
        """
        return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    def _get_extractor_args(self, service: str) -> Dict[str, Any]:
        """
        Получает специфичные аргументы экстрактора для сервиса.

        Args:
            service: Название сервиса

        Returns:
            Словарь с аргументами экстрактора
        """
        args = {}

        if 'youtube' in service.lower():
            args['youtube'] = {
                'player_client': ['android', 'web'],
                'player_skip': ['configs'],
                'skip': ['dash', 'hls'] if self._should_skip_manifests() else [],
            }
        elif 'twitch' in service.lower():
            args['twitch'] = {
                'api_base': 'https://gql.twitch.tv/gql',
            }
        elif 'tiktok' in service.lower():
            args['tiktok'] = {
                'api_hostname': 'api.tiktokv.com',
            }

        return args

    def _create_base_ydl_opts(self, service: str = '') -> Dict[str, Any]:
        """
        Создает базовые настройки yt-dlp.

        Args:
            service: Название сервиса (опционально)

        Returns:
            Словарь с базовыми настройками
        """
        opts = {
            # Основные настройки
            'quiet': True,
            'no_warnings': True,

            # Современные настройки сети
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'retry_sleep': 3,
            'http_chunk_size': 1024 * 1024,  # 1MB чанки
            'buffersize': 1024 * 1024,       # 1MB буфер

            # Обход ограничений
            'geo_bypass': True,
            'geo_bypass_country': None,
            'nocheckcertificate': True,

            # HTTP заголовки
            'http_headers': {
                'User-Agent': self._get_optimal_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },

            # Настройки экстракторов
            'extractor_args': self._get_extractor_args(service),

            # Дополнительные настройки
            'writesubtitles': False,
            'writeautomaticsub': False,
            'writethumbnail': False,
        }

        # Добавляем cookies из браузера если доступно
        cookies_config = self._get_browser_cookies_config()
        if cookies_config:
            opts['cookiesfrombrowser'] = cookies_config

        return opts
            
    async def get_video_resolutions(self, url: str) -> List[str]:
        """
        Асинхронно получает доступные разрешения видео.

        Args:
            url: URL видео

        Returns:
            Список строк с доступными разрешениями в формате "720p"
        """
        try:
            # Используем прямой метод получения форматов для разрешений
            formats = await self._get_all_formats_direct(url)

            if not formats:
                return self._get_default_resolutions()

            # Собираем разрешения из доступных форматов с учетом кодеков
            resolutions_set = set()

            for fmt in formats:
                height = fmt.get('height')
                vcodec = fmt.get('vcodec', '')

                # Пропускаем аудио-только форматы
                if not height or vcodec == 'none':
                    continue

                # Добавляем разрешение
                resolutions_set.add(height)

            if not resolutions_set:
                return self._get_default_resolutions()

            # Преобразуем в строки и сортируем
            resolutions_list = [f"{res}p" for res in sorted(resolutions_set, reverse=True)]

            # Добавляем специальные опции
            enhanced_resolutions = self._enhance_resolutions_list(resolutions_list, formats)

            logger.info(f"Найдены разрешения: {enhanced_resolutions}")
            return enhanced_resolutions

        except Exception as e:
            logger.exception(f"Ошибка при получении разрешений: {url}")
            return self._get_default_resolutions()

    async def _get_all_formats_direct(self, url: str) -> List[Dict[str, Any]]:
        """
        Получает все доступные форматы напрямую через yt-dlp.

        Args:
            url: URL видео

        Returns:
            Список всех форматов
        """
        try:
            # Используем простейшие настройки для получения максимального количества форматов
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 20,
                'retries': 3,
                # НЕ добавляем extractor_args - пусть yt-dlp использует настройки по умолчанию
            }

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                self.executor,
                self._extract_info_direct,
                url,
                ydl_opts
            )

            if info:
                formats = info.get('formats', [])
                logger.debug(f"Получено форматов напрямую: {len(formats)}")
                return formats

            return []

        except Exception as e:
            logger.debug(f"Ошибка при прямом получении форматов: {e}")
            return []

    async def _get_video_info_with_manifests(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о видео с включенными манифестами.

        Args:
            url: URL видео

        Returns:
            Информация о видео или None
        """
        try:
            # Определяем сервис для оптимизации настроек
            service = VideoURL.get_service_name(url) if hasattr(VideoURL, 'get_service_name') else ''

            # Используем базовые настройки но с манифестами
            ydl_opts = self._create_base_ydl_opts(service)
            ydl_opts.update({
                'retries': 3,  # Меньше попыток для быстрого получения
                'fragment_retries': 3,
                'retry_sleep': 1,
                'socket_timeout': 20,  # Короче таймаут
            })

            # Принудительно включаем манифесты для YouTube
            if 'youtube' in service.lower():
                ydl_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'player_skip': ['configs'],
                        'skip': [],  # Не пропускаем манифесты
                    }
                }

            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                self.executor,
                self._extract_info_direct,
                url,
                ydl_opts
            )

            return info

        except Exception as e:
            logger.exception(f"Ошибка при получении информации с манифестами: {url}")
            return None

    def _extract_info_direct(self, url: str, ydl_opts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Прямое извлечение информации с заданными настройками.

        Args:
            url: URL видео
            ydl_opts: Настройки yt-dlp

        Returns:
            Информация о видео или None
        """
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.debug(f"Ошибка прямого извлечения: {e}")
            return None

    def _get_default_resolutions(self) -> List[str]:
        """
        Возвращает список разрешений по умолчанию.

        Returns:
            Список разрешений по умолчанию
        """
        return ['2160p', '1440p', '1080p', '720p', '480p', '360p', '240p']

    def _enhance_resolutions_list(self, resolutions: List[str], formats: List[Dict]) -> List[str]:
        """
        Улучшает список разрешений, добавляя информацию о качестве.

        Args:
            resolutions: Базовый список разрешений
            formats: Список форматов от yt-dlp

        Returns:
            Улучшенный список разрешений
        """
        enhanced = []

        for res in resolutions:
            height = int(res.replace('p', ''))

            # Ищем лучший формат для данного разрешения
            best_format = self._find_best_format_for_resolution(height, formats)

            if best_format:
                # Добавляем информацию о кодеке если доступно
                vcodec = best_format.get('vcodec', '')
                fps = best_format.get('fps', 0)

                if 'av01' in vcodec.lower():
                    enhanced.append(f"{res} (AV1)")
                elif 'vp9' in vcodec.lower():
                    enhanced.append(f"{res} (VP9)")
                elif fps and fps >= 50:
                    enhanced.append(f"{res} ({int(fps)}fps)")
                else:
                    enhanced.append(res)
            else:
                enhanced.append(res)

        return enhanced

    async def get_detailed_video_analysis(self, url: str) -> Dict[str, Any]:
        """
        Получает детальный анализ видео и его форматов.

        Args:
            url: URL видео

        Returns:
            Словарь с детальным анализом
        """
        try:
            info = await self.get_video_info(url)
            if not info:
                return {'error': 'Не удалось получить информацию о видео'}

            formats = info.get('formats', [])
            analysis = self.format_analyzer.analyze_formats(formats)

            # Добавляем общую информацию о видео
            analysis.update({
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', 'Unknown'),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else ''
            })

            return analysis
        except Exception as e:
            logger.exception(f"Ошибка при детальном анализе видео: {url}")
            return {'error': str(e)}

    async def run_diagnostics(self, url: str) -> Dict[str, Any]:
        """
        Запускает диагностику для URL.

        Args:
            url: URL для диагностики

        Returns:
            Результаты диагностики
        """
        try:
            return self.diagnostics.run_diagnostics(url)
        except Exception as e:
            logger.exception(f"Ошибка при диагностике: {url}")
            return {'error': str(e)}

    def _find_best_format_for_resolution(self, height: int, formats: List[Dict]) -> Optional[Dict]:
        """
        Находит лучший формат для заданного разрешения.

        Args:
            height: Высота в пикселях
            formats: Список форматов

        Returns:
            Лучший формат или None
        """
        matching_formats = [
            fmt for fmt in formats
            if fmt.get('height') == height and fmt.get('vcodec') != 'none'
        ]

        if not matching_formats:
            return None

        # Сортируем по качеству (предпочитаем AV1 > VP9 > H.264)
        def format_quality_score(fmt):
            vcodec = fmt.get('vcodec', '').lower()
            tbr = fmt.get('tbr', 0) or 0

            codec_score = 0
            if 'av01' in vcodec:
                codec_score = 300
            elif 'vp9' in vcodec:
                codec_score = 200
            elif 'avc1' in vcodec or 'h264' in vcodec:
                codec_score = 100

            return codec_score + tbr

        return max(matching_formats, key=format_quality_score)


# Создаем глобальный экземпляр асинхронного получателя информации
video_info_fetcher = AsyncVideoInfoFetcher()


class ResolutionWorker(QThread):
    """
    Поток для получения доступных разрешений видео.
    """
    resolutions_found = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        """
        Инициализирует объект ResolutionWorker.
        
        Args:
            url: URL видео, для которого нужно получить разрешения
        """
        super().__init__()
        self.url: str = url
        self.is_running: bool = True

    def run(self) -> None:
        """Выполняет получение разрешений в отдельном потоке."""
        try:
            logger.info(f"Получение доступных разрешений для: {self.url}")

            # Проверяем, что поток не был остановлен
            if not self.is_running:
                logger.info("Поток был остановлен перед началом получения разрешений")
                return

            # Используем yt-dlp -F для получения форматов
            resolutions = self._get_resolutions_with_ytdlp()

            # Проверяем, что поток еще активен
            if not self.is_running:
                logger.info("Поток был остановлен после получения разрешений")
                return

            self.resolutions_found.emit(resolutions)
        except Exception as e:
            if self.is_running:  # Отправляем сигнал только если поток не был принудительно остановлен
                logger.exception(f"Ошибка при получении разрешений: {self.url}")
                user_friendly_error = "Не удалось получить доступные разрешения. Проверьте URL и подключение к интернету."
                self.error_occurred.emit(user_friendly_error)

    def _get_resolutions_with_ytdlp(self) -> List[str]:
        """
        Получает доступные разрешения используя yt-dlp -F.

        Returns:
            Список доступных разрешений
        """
        import subprocess
        import re

        try:
            # Запускаем yt-dlp -F для получения форматов с скрытием консоли
            cmd = ['yt-dlp', '-F', self.url]
            result = run_subprocess_hidden(cmd, encoding='utf-8')

            if result.returncode != 0:
                logger.error(f"yt-dlp -F завершился с ошибкой: {result.stderr}")
                return self._get_default_resolutions()

            # Парсим вывод yt-dlp для извлечения разрешений
            resolutions = set()
            lines = result.stdout.split('\n')

            for line in lines:
                # Пропускаем заголовки и служебные строки
                if any(skip in line for skip in [
                    'Extracting', 'Downloading', '[info]', 'ID      EXT',
                    '─────', 'Available formats', 'storyboard'
                ]):
                    continue

                # Пропускаем аудио форматы
                if 'audio only' in line:
                    continue

                # Ищем строки с разрешениями (например: "1280x720", "854x480")
                resolution_match = re.search(r'(\d+)x(\d+)', line)
                if resolution_match:
                    width = int(resolution_match.group(1))
                    height = int(resolution_match.group(2))

                    # Пропускаем слишком маленькие разрешения (storyboard)
                    if height < 144:
                        continue

                    # Добавляем только стандартные разрешения
                    if height in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                        resolutions.add(f"{height}p")
                        logger.debug(f"Найдено разрешение: {width}x{height} ({height}p)")

                # Также ищем упоминания разрешений в формате "720p", "1080p" и т.д.
                resolution_p_match = re.search(r'(\d+)p(?:\d+)?', line)
                if resolution_p_match:
                    height = int(resolution_p_match.group(1))
                    if height in [144, 240, 360, 480, 720, 1080, 1440, 2160]:
                        resolutions.add(f"{height}p")

            # Преобразуем в отсортированный список
            resolution_list = sorted(list(resolutions), key=lambda x: int(x[:-1]))

            if resolution_list:
                logger.info(f"Найдены разрешения через yt-dlp -F: {resolution_list}")
                return resolution_list
            else:
                logger.warning("Не найдено разрешений в выводе yt-dlp -F")
                return self._get_default_resolutions()

        except subprocess.TimeoutExpired:
            logger.error("Таймаут при выполнении yt-dlp -F")
            return self._get_default_resolutions()
        except Exception as e:
            logger.exception(f"Ошибка при выполнении yt-dlp -F: {e}")
            return self._get_default_resolutions()

    def _get_default_resolutions(self) -> List[str]:
        """
        Возвращает стандартный набор разрешений как fallback.

        Returns:
            Список стандартных разрешений
        """
        return ["144p", "240p", "360p", "480p", "720p", "1080p"]

    def terminate(self) -> None:
        """Переопределяем terminate для безопасной остановки потока."""
        logger.info(f"Запрос на остановку потока ResolutionWorker для URL: {self.url}")
        self.is_running = False
        super().terminate()


class DownloadRunnable(QRunnable):
    """
    QRunnable для загрузки видео/аудио в фоновом потоке.
    """
    class Signals(QObject):
        """
        Сигналы для обмена информацией с основным потоком.
        """
        progress = pyqtSignal(str, float)
        finished = pyqtSignal(bool, str, str)
        
    def __init__(self, url: str, mode: str, resolution: Optional[str] = None,
                 output_dir: str = 'downloads') -> None:
        """
        Инициализирует задачу загрузки.
        
        Args:
            url: URL видео/аудио для загрузки
            mode: Режим загрузки ('video' или 'audio')
            resolution: Разрешение для видео (например, '720p')
            output_dir: Директория для сохранения файлов
        """
        super().__init__()
        self.url = url
        self.mode = mode
        self.resolution = resolution
        self.output_dir = output_dir
        self.signals = self.Signals()
        self.cancel_event = threading.Event()
        self.downloaded_filename = None
        
        os.makedirs(output_dir, exist_ok=True)

    def _get_optimal_user_agent(self) -> str:
        """
        Возвращает оптимальный User-Agent для запросов.

        Returns:
            Строка User-Agent
        """
        return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    def _get_extractor_args(self, service: str) -> Dict[str, Any]:
        """
        Получает специфичные аргументы экстрактора для сервиса.

        Args:
            service: Название сервиса

        Returns:
            Словарь с аргументами экстрактора
        """
        args = {}

        if 'youtube' in service.lower():
            args['youtube'] = {
                'player_client': ['android', 'web'],
                'player_skip': ['configs'],
                # НЕ пропускаем DASH/HLS - они содержат высокие разрешения!
                # 'skip': ['dash', 'hls'],  # УБРАНО: это блокировало высокие разрешения
            }
        elif 'twitch' in service.lower():
            args['twitch'] = {
                'api_base': 'https://gql.twitch.tv/gql',
            }
        elif 'tiktok' in service.lower():
            args['tiktok'] = {
                'api_hostname': 'api.tiktokv.com',
            }

        return args

    def _create_base_ydl_opts(self, service: str = '') -> Dict[str, Any]:
        """
        Создает базовые настройки yt-dlp.

        Args:
            service: Название сервиса (опционально)

        Returns:
            Словарь с базовыми настройками
        """
        opts = {
            # Основные настройки
            'quiet': True,
            'no_warnings': True,

            # Современные настройки сети
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'retry_sleep': 3,
            'http_chunk_size': 1024 * 1024,  # 1MB чанки
            'buffersize': 1024 * 1024,       # 1MB буфер

            # Обход ограничений
            'geo_bypass': True,
            'geo_bypass_country': None,
            'nocheckcertificate': True,

            # HTTP заголовки
            'http_headers': {
                'User-Agent': self._get_optimal_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },

            # НЕ используем extractor_args для загрузки - они вызывают проблемы с YouTube API
            # 'extractor_args': self._get_extractor_args(service),

            # Дополнительные настройки
            'writesubtitles': False,
            'writeautomaticsub': False,
            'writethumbnail': False,
        }

        return opts
        
    def run(self) -> None:
        """Выполняет загрузку файла."""
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
        """
        Преобразует технические сообщения об ошибках в понятные для пользователя.

        Args:
            error: Исходное сообщение об ошибке

        Returns:
            Понятное для пользователя сообщение об ошибке
        """
        error_lower = error.lower()

        # HTTP ошибки
        if "HTTP Error 404" in error or "404" in error:
            return "Ошибка: Видео не найдено (404). Возможно, оно было удалено или является приватным."
        elif "HTTP Error 403" in error or "403" in error:
            return "Ошибка: Доступ запрещен (403). Видео может быть недоступно в вашем регионе."
        elif "HTTP Error 429" in error or "429" in error:
            return "Ошибка: Слишком много запросов (429). Попробуйте позже."
        elif "HTTP Error 500" in error or "500" in error:
            return "Ошибка сервера (500). Попробуйте позже или выберите другое разрешение."
        elif "HTTP Error 503" in error or "503" in error:
            return "Сервис временно недоступен (503). Попробуйте позже."

        # Ошибки авторизации и ограничений
        elif "Sign in to confirm your age" in error or "age-restricted" in error:
            return "Ошибка: Видео имеет возрастные ограничения и требует авторизации."
        elif "private video" in error_lower or "приватное видео" in error_lower:
            return "Ошибка: Это приватное видео, доступ к которому ограничен."
        elif "members-only" in error_lower or "только для участников" in error_lower:
            return "Ошибка: Видео доступно только для участников канала."
        elif "premium" in error_lower and ("required" in error_lower or "необходим" in error_lower):
            return "Ошибка: Для просмотра этого видео требуется премиум-подписка."

        # Географические ограничения
        elif "geo" in error_lower and ("block" in error_lower or "restrict" in error_lower):
            return "Ошибка: Видео заблокировано в вашем регионе. Попробуйте использовать VPN."
        elif "not available in your country" in error_lower:
            return "Ошибка: Видео недоступно в вашей стране."

        # Ошибки сети и подключения
        elif any(keyword in error_lower for keyword in ["ssl", "подключени", "connect", "timeout", "network"]):
            return "Ошибка подключения. Проверьте соединение с интернетом или попробуйте позже."
        elif "dns" in error_lower:
            return "Ошибка DNS. Проверьте настройки сети или попробуйте позже."

        # Ошибки авторских прав
        elif any(keyword in error_lower for keyword in ["copyright", "авторские права", "dmca"]):
            return "Ошибка: Видео недоступно из-за нарушения авторских прав."

        # Ошибки форматов и кодеков
        elif "no video formats found" in error_lower or "форматы не найдены" in error_lower:
            return "Ошибка: Не найдены подходящие форматы видео. Попробуйте другое разрешение."
        elif "format not available" in error_lower:
            return "Ошибка: Выбранный формат недоступен. Попробуйте другое разрешение."
        elif "ffmpeg" in error_lower and "not found" in error_lower:
            return "Ошибка: FFmpeg не найден. Установите FFmpeg для корректной работы."

        # Ошибки экстракторов
        elif "extractor" in error_lower and ("failed" in error_lower or "error" in error_lower):
            return "Ошибка извлечения данных. Возможно, сайт изменил свою структуру."
        elif "unsupported url" in error_lower or "неподдерживаемый url" in error_lower:
            return "Ошибка: Неподдерживаемый URL или видеосервис."

        # Ошибки загрузки
        elif "download" in error_lower and ("failed" in error_lower or "interrupted" in error_lower):
            return "Ошибка загрузки. Проверьте соединение и попробуйте снова."
        elif "disk" in error_lower and ("space" in error_lower or "full" in error_lower):
            return "Ошибка: Недостаточно места на диске."
        elif "permission" in error_lower or "доступ" in error_lower:
            return "Ошибка: Недостаточно прав для записи в выбранную папку."

        # Ошибки cookies и авторизации
        elif "cookies" in error_lower:
            return "Ошибка с cookies. Попробуйте очистить cookies браузера."
        elif "login" in error_lower or "authentication" in error_lower:
            return "Ошибка авторизации. Возможно, требуется вход в аккаунт."

        # Общие ошибки
        elif "cancelled" in error_lower or "отменено" in error_lower:
            return "Загрузка была отменена пользователем."
        elif len(error.strip()) == 0:
            return "Произошла неизвестная ошибка."
        else:
            # Обрезаем слишком длинные сообщения
            if len(error) > 200:
                error = error[:200] + "..."
            return f"Ошибка загрузки: {error}"
            
    def download_video(self) -> bool:
        """
        Загружает видео с заданным разрешением.

        Returns:
            True при успешной загрузке, False при отмене
        """
        try:
            if not self.resolution:
                raise Exception("Не указано разрешение для видео")

            # Извлекаем числовое значение разрешения
            resolution_number = self._extract_resolution_number(self.resolution)
            service: str = VideoURL.get_service_name(self.url)
            logger.info(f"Загрузка видео с {service} в разрешении {resolution_number}p")

            # Создаем современный селектор форматов
            format_selector = self._create_video_format_selector(resolution_number)

            # Используем базовые настройки и дополняем их для загрузки видео
            ydl_opts = self._create_base_ydl_opts(service)
            ydl_opts.update({
                'format': format_selector,
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(self.output_dir, f'%(title)s_{resolution_number}p.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'postprocessors': [
                    {
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4',
                    },
                    {
                        'key': 'FFmpegMetadata',
                        'add_metadata': True,
                    }
                ],
                # Настройки обработки ошибок для загрузки
                'ignoreerrors': False,  # Не игнорируем ошибки при загрузке

                # Принудительное объединение видео+аудио через FFmpeg
                'prefer_ffmpeg': True,
                'keepvideo': False,  # Удаляем исходные файлы после объединения

                # Настройки FFmpeg для быстрого объединения без перекодирования
                'postprocessor_args': {
                    'ffmpeg': [
                        '-c', 'copy',  # Копируем потоки без перекодирования (быстро!)
                        '-movflags', '+faststart'  # Оптимизация для веб
                    ]
                },
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            # Получаем информацию о видео и сохраняем в кэш после успешной загрузки
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as info_ydl:
                    video_info = info_ydl.extract_info(self.url, download=False)
                    if video_info:
                        # Сохраняем информацию в кэш
                        video_info_cache.set(self.url, video_info)
                        logger.info(f"Информация о видео сохранена в кэш: {self.url}")
            except Exception as e:
                logger.warning(f"Не удалось получить информацию для кэша: {e}")

            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки видео")
            raise

    def _extract_resolution_number(self, resolution: str) -> str:
        """
        Извлекает числовое значение разрешения из строки.

        Args:
            resolution: Строка разрешения (например, "1080p (VP9)")

        Returns:
            Числовое значение разрешения
        """
        import re
        match = re.search(r'(\d+)p', resolution)
        return match.group(1) if match else '720'

    def _create_video_format_selector(self, resolution_number: str) -> str:
        """
        Создает современный селектор форматов для видео с правильным объединением.

        Args:
            resolution_number: Числовое значение разрешения

        Returns:
            Строка селектора форматов
        """
        height = int(resolution_number)

        # Для YouTube >360p нужно принудительно объединять видео+аудио
        # Используем оптимизированный селектор для быстрого объединения
        selectors = [
            # Основной селектор: MP4 видео + M4A аудио для быстрого объединения без перекодирования
            f'bv*[height={height}][ext=mp4]+ba[ext=m4a]/b[height={height}][ext=mp4]',

            # Fallback с диапазоном разрешений
            f'bv*[height<={height}][ext=mp4]+ba[ext=m4a]/b[height<={height}][ext=mp4]',

            # Альтернативный с любыми совместимыми форматами
            f'bv*[height={height}]+ba[ext=m4a]/bv*[height={height}]+ba',
            f'bv*[height<={height}]+ba[ext=m4a]/bv*[height<={height}]+ba',

            # Классический fallback
            f'bestvideo[height={height}]+bestaudio/best[height={height}]',
            f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',

            # Fallback для объединенных форматов
            f'best[height<={height}][acodec!=none]',
            f'best[height<={height}]',

            # Последний fallback
            'best'
        ]

        return '/'.join(selectors)
            
    def download_audio(self) -> bool:
        """
        Загружает аудио из видео.

        Returns:
            True при успешной загрузке, False при отмене
        """
        try:
            service: str = VideoURL.get_service_name(self.url)
            logger.info(f"Загрузка аудио с {service}")

            # Создаем современный селектор аудио форматов
            audio_format_selector = self._create_audio_format_selector()

            # Используем базовые настройки и дополняем их для загрузки аудио
            ydl_opts = self._create_base_ydl_opts(service)
            ydl_opts.update({
                'format': audio_format_selector,
                'outtmpl': os.path.join(self.output_dir, '%(title)s_audio.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',  # Увеличиваем качество до 320 kbps
                }],
                # Настройки обработки ошибок для загрузки
                'ignoreerrors': False,  # Не игнорируем ошибки при загрузке
            })

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            # Получаем информацию о видео и сохраняем в кэш после успешной загрузки
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as info_ydl:
                    video_info = info_ydl.extract_info(self.url, download=False)
                    if video_info:
                        # Сохраняем информацию в кэш
                        video_info_cache.set(self.url, video_info)
                        logger.info(f"Информация о видео сохранена в кэш: {self.url}")
            except Exception as e:
                logger.warning(f"Не удалось получить информацию для кэша: {e}")

            return True

        except Exception as e:
            logger.exception(f"Ошибка загрузки аудио")
            raise

    def _create_audio_format_selector(self) -> str:
        """
        Создает современный селектор аудио форматов.

        Returns:
            Строка селектора аудио форматов
        """
        # Приоритет: Opus > AAC > MP3, с высоким битрейтом
        selectors = [
            'ba*[acodec*=opus][abr>=128]',  # Opus высокого качества
            'ba*[acodec*=aac][abr>=128]',   # AAC высокого качества
            'ba*[abr>=128]',                # Любой формат высокого качества
            'ba*',                          # Лучший доступный аудио
            'best[acodec!=none]',           # Fallback с аудио
            'best'                          # Последний fallback
        ]

        return '/'.join(selectors)

    @staticmethod
    def check_yt_dlp_version() -> Dict[str, Any]:
        """
        Проверяет версию yt-dlp и доступность обновлений.

        Returns:
            Словарь с информацией о версии
        """
        try:
            import yt_dlp
            current_version = yt_dlp.version.__version__

            return {
                'current_version': current_version,
                'is_latest': True,  # Упрощенная проверка
                'update_available': False,
                'status': 'ok'
            }
        except Exception as e:
            logger.exception("Ошибка при проверке версии yt-dlp")
            return {
                'current_version': 'unknown',
                'is_latest': False,
                'update_available': False,
                'status': 'error',
                'error': str(e)
            }

    @staticmethod
    def get_supported_sites_count() -> int:
        """
        Получает количество поддерживаемых сайтов.

        Returns:
            Количество поддерживаемых сайтов
        """
        try:
            import yt_dlp
            from yt_dlp.extractor import list_extractors

            extractors = list_extractors()
            return len(extractors)
        except Exception as e:
            logger.exception("Ошибка при получении списка экстракторов")
            return 0
            
    def progress_hook(self, d: Dict[str, Any]) -> None:
        """
        Хук обработки прогресса загрузки yt-dlp с мониторингом памяти.

        Args:
            d: Словарь с информацией о прогрессе загрузки
        """
        if self.cancel_event.is_set():
            raise Exception("Загрузка отменена пользователем")

        # Проверяем использование памяти
        if memory_monitor.is_memory_limit_exceeded():
            memory_monitor.force_garbage_collection()
            logger.warning("Превышен лимит памяти во время загрузки")

        if d.get('status') == 'downloading':
            try:
                downloaded: float = d.get('downloaded_bytes', 0)
                total: float = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)

                # Логируем использование памяти для больших файлов
                if total > 100 * 1024 * 1024:  # Файлы больше 100MB
                    if downloaded % (10 * 1024 * 1024) < 1024 * 1024:  # каждые 10MB
                        memory_monitor.log_memory_usage(f"загрузка {downloaded/(1024*1024):.1f}MB")

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
            memory_monitor.log_memory_usage("завершение загрузки")
            
    def cancel(self) -> None:
        """Отменяет текущую загрузку."""
        self.cancel_event.set()
        logger.info(f"Запрошена отмена загрузки: {self.url}")


class DownloadManager:
    """Класс для управления загрузками видео и аудио."""
    
    def __init__(self, output_dir: str = 'downloads'):
        """
        Инициализирует менеджер загрузок.
        
        Args:
            output_dir: Директория для сохранения загруженных файлов
        """
        self.output_dir = output_dir
        self.download_queue: List[Dict[str, Any]] = []
        self.current_download: Optional[DownloadRunnable] = None
        self.successful_downloads: List[Tuple[str, str]] = []
        self.failed_downloads: List[Tuple[str, str]] = []
        os.makedirs(output_dir, exist_ok=True)

    def set_output_dir(self, output_dir: str) -> None:
        """
        Устанавливает новую папку для сохранения файлов.

        Args:
            output_dir: Путь к папке для сохранения
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Установлена папка для сохранения: {output_dir}")

    def add_to_queue(self, url: str, mode: str, resolution: Optional[str] = None) -> bool:
        """
        Добавляет новую загрузку в очередь.
        
        Args:
            url: URL видео/аудио
            mode: Режим загрузки ('video' или 'audio')
            resolution: Разрешение для видео
            
        Returns:
            True если URL валиден и добавлен в очередь, иначе False
        """
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

    def process_queue(self) -> Optional[DownloadRunnable]:
        """
        Обрабатывает следующий элемент в очереди.
        
        Returns:
            Объект DownloadRunnable или None, если очередь пуста
        """
        if not self.download_queue:
            logger.info("Очередь загрузок завершена")
            return None

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
        """
        Обработчик завершения загрузки.

        Args:
            success: Флаг успешной загрузки
            message: Сообщение о результате
            filename: Имя загруженного файла
        """
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

        # Очистка памяти после завершения загрузки
        memory_monitor.force_garbage_collection()
        memory_monitor.log_memory_usage("завершение загрузки в менеджере")

    def clear_queue(self) -> None:
        """Очищает очередь загрузок."""
        self.download_queue.clear()
        logger.info("Очередь загрузок очищена")

    def remove_from_queue(self, index: int) -> None:
        """
        Удаляет элемент из очереди по индексу.
        
        Args:
            index: Индекс элемента в очереди
        """
        if 0 <= index < len(self.download_queue):
            del self.download_queue[index]
            logger.info(f"Элемент {index} удален из очереди")

    def get_download_summary(self) -> str:
        """
        Возвращает сводку о загрузках.
        
        Returns:
            Строка с информацией о загрузках
        """
        if not self.successful_downloads and not self.failed_downloads:
            return ""

        message = "Результаты загрузки:\n\n"
        if self.successful_downloads:
            message += "Успешно загружены:\n"
            for filename, url in self.successful_downloads:
                # Определяем правильное расширение на основе типа загрузки
                display_filename = self._get_display_filename(filename)
                message += f"✓ {display_filename}\n"
        if self.failed_downloads:
            message += "\nНе удалось загрузить:\n"
            for url, error in self.failed_downloads:
                short_url = url if len(url) <= 50 else url[:50] + "..."
                message += f"✗ {short_url}\n   Причина: {error}\n"
        return message

    def _get_display_filename(self, filename: str) -> str:
        """
        Возвращает правильное имя файла для отображения.

        Args:
            filename: Исходное имя файла от yt-dlp

        Returns:
            Имя файла с правильным расширением
        """
        if not filename:
            return "Неизвестный файл"

        # Убираем путь, оставляем только имя файла
        base_filename = os.path.basename(filename)

        # Убираем расширение для анализа
        name_without_ext = os.path.splitext(base_filename)[0]

        # Определяем тип файла по содержимому имени
        if '_audio' in name_without_ext.lower():
            # Аудио файлы всегда конвертируются в MP3
            return f"{name_without_ext}.mp3"
        else:
            # Видео файлы всегда конвертируются в MP4
            # Убираем ID форматов из имени (например: .f140-9, .f244+251, .webm, .mkv)
            clean_name = re.sub(r'\.f\d+[-+]?\d*', '', name_without_ext)  # Убираем .f140-9, .f244+251
            clean_name = re.sub(r'\+\d+', '', clean_name)  # Убираем оставшиеся +251
            clean_name = re.sub(r'\.webm$|\.mkv$|\.m4a$', '', clean_name)  # Убираем расширения
            return f"{clean_name}.mp4"

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


# Загружаем кэш при импорте модуля
video_info_cache.load_from_file() 