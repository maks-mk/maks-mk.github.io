#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Video Downloader - приложение для загрузки видео и аудио с различных видеохостингов.
Автор: MaksK
Версия: 1.098
"""

import os
import sys
import traceback
import logging
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

# Импортируем наши модули
from utils import setup_logging, check_ffmpeg
# Импортируем обновленный интерфейс с темной темой
from gui_dark import VideoDownloaderUI


def show_error_dialog(error_type, error_value, error_tb):
    """
    Показывает диалоговое окно с информацией о необработанном исключении.
    
    Args:
        error_type: Тип исключения
        error_value: Значение исключения
        error_tb: Трассировка стека
    """
    logger = logging.getLogger('VideoDownloader')
    logger.critical(f"Необработанное исключение: {error_type}: {error_value}")
    
    error_message = f"{error_type}: {error_value}"
    error_details = "".join(traceback.format_tb(error_tb))
    
    logger.critical(f"Детали исключения:\n{error_details}")
    
    try:
        # Пытаемся показать диалоговое окно
        if QApplication.instance():
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Ошибка приложения")
            msg_box.setText("В приложении произошла критическая ошибка:")
            msg_box.setInformativeText(error_message)
            msg_box.setDetailedText(error_details)
            msg_box.exec()
    except Exception as e:
        # Если не удалось показать диалоговое окно, записываем ошибку в лог
        logger.critical(f"Не удалось показать диалоговое окно с ошибкой: {e}")
    
    # В любом случае записываем ошибку в файл crash.log
    try:
        with open("crash.log", "a", encoding="utf-8") as f:
            f.write(f"[{logging.Formatter().formatTime(None)}] {error_type}: {error_value}\n")
            f.write(f"Детали:\n{error_details}\n\n")
    except Exception as e:
        logger.critical(f"Не удалось записать информацию о сбое в файл: {e}")


def main():
    """
    Основная функция для запуска приложения.
    Настраивает логирование, проверяет зависимости и запускает интерфейс.
    """
    # Настраиваем логирование
    logger = setup_logging()
    logger.info("Запуск приложения Video Downloader")
    
    # Устанавливаем обработчик исключений
    sys.excepthook = show_error_dialog
    
    # Создаем директорию для загрузок, если её нет
    os.makedirs("downloads", exist_ok=True)
    
    # Проверяем наличие ffmpeg
    if not check_ffmpeg():
        logger.warning("ffmpeg не найден. Некоторые функции могут работать некорректно.")
    
    # Запускаем приложение
    app = QApplication(sys.argv)
    app.setApplicationName("Video Downloader")
    app.setApplicationVersion("1.098")
    
    # Отключаем "мультикасание" на Windows, которое может вызывать проблемы
    os.environ["QT_QUICK_CONTROLS_HOVER_ENABLED"] = "0"
    
    # Устанавливаем стиль приложения
    app.setStyle("Fusion")  # Единый стиль для всех платформ
    
    # Создаем и показываем основное окно с улучшенным темным интерфейсом
    main_window = VideoDownloaderUI()
    main_window.show()
    
    # Запускаем основной цикл событий
    return app.exec()


if __name__ == "__main__":
    sys.exit(main()) 