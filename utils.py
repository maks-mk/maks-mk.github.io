import os
import sys
import logging
from datetime import datetime
from typing import Tuple, Optional
from logging.handlers import RotatingFileHandler
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


def setup_logging():
    """
    Настраивает систему логирования приложения.
    
    Создает директорию для логов, настраивает форматирование
    и ротацию файлов логов.
    """
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"video_downloader_{current_date}.log")
    
    logger = logging.getLogger('VideoDownloader')
    logger.setLevel(logging.INFO)
    
    # Если обработчики уже настроены, не добавляем новые
    if logger.handlers:
        return logger
    
    # Настраиваем файловый обработчик с ротацией
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(funcName)s(%(lineno)d): %(message)s'
    ))
    logger.addHandler(file_handler)
    
    # Добавляем обработчик для вывода в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(funcName)s(%(lineno)d): %(message)s'
    ))
    logger.addHandler(console_handler)
    
    return logger


def get_resource_path(relative_path: str) -> str:
    """
    Получает абсолютный путь к ресурсу, корректно работает как в режиме разработки,
    так и в скомпилированном PyInstaller EXE.
    
    Args:
        relative_path: Относительный путь к ресурсу
        
    Returns:
        Абсолютный путь к ресурсу
    """
    try:
        # PyInstaller создает временную директорию и сохраняет путь в _MEIPASS
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)
    except Exception as e:
        logging.getLogger('VideoDownloader').error(f"Ошибка при определении пути ресурса {relative_path}: {e}")
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def load_image(image_name: str, size: Tuple[int, int] = (100, 100)) -> Tuple[bool, Optional[QPixmap], str]:
    """
    Загружает изображение с проверкой различных расширений.
    
    Args:
        image_name: Имя файла без расширения
        size: Размер для масштабирования (ширина, высота)
        
    Returns:
        Tuple из (успех загрузки, pixmap или None, путь к файлу)
    """
    logger = logging.getLogger('VideoDownloader')
    # Изменяем порядок расширений, чтобы PNG был первым
    extensions = [".png", ".jpeg", ".jpg", ".gif", ".ico"]
    
    for ext in extensions:
        image_path = get_resource_path(f"{image_name}{ext}")
        if os.path.exists(image_path):
            try:
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    # Масштабируем изображение до указанного размера
                    scaled_pixmap = pixmap.scaled(
                        size[0], size[1], 
                        Qt.AspectRatioMode.KeepAspectRatio, 
                        Qt.TransformationMode.SmoothTransformation
                    )
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
    logger = logging.getLogger('VideoDownloader')
    image_path = get_resource_path("vid1.png")
    logger.info(f"Загрузка логотипа из: {image_path}")
    
    if os.path.exists(image_path):
        try:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    size[0], size[1], 
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                logger.info(f"Логотип успешно загружен: {image_path}")
                return True, scaled_pixmap, image_path
            else:
                logger.warning(f"Логотип не удалось загрузить (пустой pixmap): {image_path}")
        except Exception as e:
            logger.exception(f"Ошибка при загрузке логотипа: {image_path}")
    else:
        logger.warning(f"Файл логотипа не найден: {image_path}")
    
    return False, None, ""


def check_ffmpeg() -> bool:
    """
    Проверяет наличие ffmpeg и ffprobe в системе.
    
    Returns:
        True, если оба компонента найдены, иначе False.
    """
    import shutil
    logger = logging.getLogger('VideoDownloader')
    
    ffmpeg_exists = shutil.which('ffmpeg') is not None
    ffprobe_exists = shutil.which('ffprobe') is not None
    
    logger.info(f"Проверка компонентов: ffmpeg: {ffmpeg_exists}, ffprobe: {ffprobe_exists}")
    return ffmpeg_exists and ffprobe_exists


# Настраиваем логирование при импорте модуля
logger = setup_logging() 