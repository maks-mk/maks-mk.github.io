import os
import threading
import logging
import hashlib
import json
from typing import Dict, Any, Optional, List, Tuple, Set, Union
from enum import Enum
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import asyncio

from PyQt6.QtCore import QRunnable, QObject, pyqtSignal, QThread
import yt_dlp

from validators import VideoURL

logger = logging.getLogger('VideoDownloader')


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


class VideoInfoCache:
    """Класс для кэширования информации о видео."""
    
    def __init__(self, max_size: int = 100):
        """
        Инициализирует кэш информации о видео.
        
        Args:
            max_size: Максимальный размер кэша
        """
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        
    def get(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о видео из кэша.
        
        Args:
            url: URL видео
            
        Returns:
            Информация о видео или None, если не найдена в кэше
        """
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


# Создаем глобальный экземпляр кэша
video_info_cache = VideoInfoCache()


class AsyncVideoInfoFetcher:
    """Класс для асинхронного получения информации о видео."""
    
    def __init__(self):
        """Инициализирует фетчер информации о видео."""
        self.loop = None
        self.executor = ThreadPoolExecutor(max_workers=4)
        
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
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except Exception as e:
            logger.exception(f"Ошибка при получении информации о видео: {url}")
            return None
            
    async def get_video_resolutions(self, url: str) -> List[str]:
        """
        Асинхронно получает доступные разрешения видео.
        
        Args:
            url: URL видео
            
        Returns:
            Список строк с доступными разрешениями в формате "720p"
        """
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
                
            # Создаем новый event loop для асинхронных операций
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Получаем разрешения асинхронно
            resolutions = loop.run_until_complete(
                video_info_fetcher.get_video_resolutions(self.url)
            )
            
            # Закрываем loop
            loop.close()
            
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
        """
        Загружает видео с заданным разрешением.
        
        Returns:
            True при успешной загрузке, False при отмене
        """
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
        """
        Загружает аудио из видео.
        
        Returns:
            True при успешной загрузке, False при отмене
        """
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
        """
        Хук обработки прогресса загрузки yt-dlp.
        
        Args:
            d: Словарь с информацией о прогрессе загрузки
        """
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


# Загружаем кэш при импорте модуля
video_info_cache.load_from_file() 