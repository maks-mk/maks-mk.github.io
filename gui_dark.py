#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import logging
from typing import Dict, Any, Optional, List, Tuple, Set, Union

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QComboBox, QRadioButton, 
    QListWidget, QProgressBar, QMessageBox, QApplication,
    QButtonGroup, QSplitter, QStatusBar, QSizePolicy, QToolTip
)
from PyQt6.QtCore import Qt, QThreadPool, QSettings, pyqtSignal, QSize
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QColor, QIcon

import qtawesome as qta

from utils import load_app_logo, load_image, setup_logging, get_resource_path
from validators import VideoURL
from downloader import (
    DownloadManager, ResolutionWorker, 
    video_info_cache, DownloadMode
)

logger = logging.getLogger('VideoDownloader')


class ThemeManager:
    """Класс для управления темой приложения."""
    
    # Темная тема по умолчанию
    DARK_THEME = {
        'background': '#1e1e1e',
        'secondary_background': '#252526',
        'foreground': '#f5f5f5',
        'primary': '#007acc',
        'secondary': '#651fff',
        'success': '#00c853',
        'warning': '#ffd600',
        'error': '#d50000',
        'card': '#2d2d2d',
        'border': '#3e3e3e',
        'hover': '#3c3c3c',
        'button': '#2979ff',
        'button_text': '#ffffff',
        'button_hover': '#0d47a1',
        'icon': '#b0b0b0'
    }
    
    @staticmethod
    def get_theme() -> Dict[str, str]:
        """
        Возвращает цветовую схему темной темы.
        
        Returns:
            Словарь с цветовой схемой
        """
        return ThemeManager.DARK_THEME
        
    @staticmethod
    def apply_theme(widget: QWidget) -> None:
        """
        Применяет темную тему к виджету.
        
        Args:
            widget: Виджет, к которому применяется тема
        """
        colors = ThemeManager.get_theme()
        
        stylesheet = f"""
        QWidget {{
            background-color: {colors['background']};
            color: {colors['foreground']};
        }}
        
        QSplitter::handle {{
            background-color: {colors['border']};
        }}
        
        QLineEdit, QComboBox, QRadioButton {{
            padding: 8px;
            border: 1px solid {colors['border']};
            border-radius: 4px;
            background-color: {colors['secondary_background']};
        }}
        
        QLineEdit:focus {{
            border: 1px solid {colors['primary']};
        }}
        
        QPushButton {{
            background-color: {colors['button']};
            color: {colors['button_text']};
            font-weight: bold;
            padding: 8px;
            border: none;
            border-radius: 4px;
        }}
        
        QPushButton:hover {{
            background-color: {colors['button_hover']};
        }}
        
        QPushButton:pressed {{
            background-color: {colors['primary']};
        }}
        
        QProgressBar {{
            border: 1px solid {colors['border']};
            border-radius: 4px;
            text-align: center;
            color: {colors['foreground']};
            font-weight: bold;
            background-color: {colors['secondary_background']};
        }}
        
        QProgressBar::chunk {{
            background-color: {colors['primary']};
            width: 1px;
        }}
        
        QListWidget {{
            background-color: {colors['secondary_background']};
            border: 1px solid {colors['border']};
            border-radius: 4px;
            padding: 4px;
        }}
        
        QListWidget::item {{
            padding: 4px;
            border-radius: 2px;
        }}
        
        QListWidget::item:selected {{
            background-color: {colors['primary']};
            color: {colors['button_text']};
        }}
        
        QListWidget::item:hover:!selected {{
            background-color: {colors['hover']};
        }}
        
        QLabel#statusLabel {{
            font-weight: bold;
            padding: 4px;
            border-radius: 4px;
            background-color: {colors['secondary_background']};
        }}
        
        QStatusBar {{
            background-color: {colors['secondary_background']};
            color: {colors['foreground']};
            border-top: 1px solid {colors['border']};
        }}
        
        QToolTip {{
            background-color: {colors['card']};
            color: {colors['foreground']};
            border: 1px solid {colors['border']};
            padding: 4px;
        }}
        """
        widget.setStyleSheet(stylesheet)


class VideoDownloaderUI(QMainWindow):
    """Главное окно приложения для загрузки видео."""
    
    def __init__(self) -> None:
        """Инициализирует пользовательский интерфейс."""
        super().__init__()
        self.thread_pool = QThreadPool()
        self.download_manager = DownloadManager()
        self.init_ui()
        self.load_settings()
        logger.info("Приложение запущено и готово к работе")
        
    def init_ui(self) -> None:
        """Инициализирует компоненты пользовательского интерфейса."""
        # Основное окно
        self.setWindowTitle("Video Downloader by MaksK")
        self.setGeometry(100, 100, 1000, 700)
        
        # Установка иконки
        success, icon_pixmap, _ = load_app_logo((32, 32))
        if success:
            self.setWindowIcon(QIcon(icon_pixmap))
        
        # Основной виджет с разделителем
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)  # Используем горизонтальную компоновку для панелей
        
        # Создаем разделитель для двух панелей
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Левая панель (форма загрузки)
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        
        # Верхнее лого и заголовок
        header_layout = QHBoxLayout()
        success, logo_pixmap, _ = load_app_logo((80, 80))
        if success:
            logo_label = QLabel()
            logo_label.setPixmap(logo_pixmap)
            header_layout.addWidget(logo_label)
        
        title_label = QLabel("Video/Audio Downloader")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        header_layout.addWidget(title_label, 1)
        left_layout.addLayout(header_layout)
        
        # Форма ввода URL
        url_layout = QHBoxLayout()
        url_label = QLabel("URL видео:")
        url_layout.addWidget(url_label)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Вставьте ссылку на видео")
        self.url_input.setDragEnabled(True)
        
        # Подключаем обработку нажатия Enter в поле ввода URL
        self.url_input.returnPressed.connect(self.on_url_changed)
        
        # Добавляем иконку для поля ввода URL
        url_icon = qta.icon('fa5s.link', color=ThemeManager.get_theme()['icon'])
        self.url_input.addAction(url_icon, QLineEdit.ActionPosition.LeadingPosition)
        
        # Добавляем кнопку для проверки URL
        check_url_button = QPushButton("Проверить")
        check_url_icon = qta.icon('fa5s.search', color=ThemeManager.get_theme()['button_text'])
        check_url_button.setIcon(check_url_icon)
        check_url_button.setToolTip("Проверить доступные разрешения для видео")
        check_url_button.clicked.connect(self.on_url_changed)
        
        url_layout.addWidget(self.url_input, 3)
        url_layout.addWidget(check_url_button)
        left_layout.addLayout(url_layout)
        
        # Режим загрузки и разрешение
        mode_res_layout = QHBoxLayout()
        
        # Режим загрузки (видео/аудио)
        mode_group_box = QWidget()
        mode_group_layout = QVBoxLayout(mode_group_box)
        mode_group_label = QLabel("Режим загрузки:")
        mode_group_layout.addWidget(mode_group_label)
        
        mode_layout = QHBoxLayout()
        self.video_radio = QRadioButton("Видео")
        self.audio_radio = QRadioButton("Аудио")
        self.video_radio.setChecked(True)
        
        # Добавляем иконки к радиокнопкам
        video_icon = qta.icon('fa5s.video', color=ThemeManager.get_theme()['icon'])
        audio_icon = qta.icon('fa5s.music', color=ThemeManager.get_theme()['icon'])
        
        self.video_radio.setIcon(video_icon)
        self.audio_radio.setIcon(audio_icon)
        
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.video_radio)
        mode_group.addButton(self.audio_radio)
        
        mode_layout.addWidget(self.video_radio)
        mode_layout.addWidget(self.audio_radio)
        mode_group_layout.addLayout(mode_layout)
        
        mode_res_layout.addWidget(mode_group_box)
        
        # Выбор разрешения
        resolution_group_box = QWidget()
        self.resolution_layout = QVBoxLayout(resolution_group_box)
        resolution_label = QLabel("Разрешение:")
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(['1080p', '720p', '480p', '360p', '240p'])
        self.resolution_combo.setCurrentText('720p')
        
        self.resolution_layout.addWidget(resolution_label)
        self.resolution_layout.addWidget(self.resolution_combo)
        
        mode_res_layout.addWidget(resolution_group_box)
        
        # Обработчик изменения режима
        self.video_radio.toggled.connect(self.on_mode_changed)
        self.audio_radio.toggled.connect(self.on_mode_changed)
        
        left_layout.addLayout(mode_res_layout)

        # Выбор папки для сохранения
        folder_layout = QHBoxLayout()
        folder_label = QLabel("Папка сохранения:")
        folder_layout.addWidget(folder_label)

        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Выберите папку для сохранения файлов")
        self.folder_input.setReadOnly(True)

        # Добавляем иконку для поля папки
        folder_icon = qta.icon('fa5s.folder', color=ThemeManager.get_theme()['icon'])
        self.folder_input.addAction(folder_icon, QLineEdit.ActionPosition.LeadingPosition)

        # Кнопка выбора папки
        browse_button = QPushButton("Обзор")
        browse_icon = qta.icon('fa5s.folder-open', color=ThemeManager.get_theme()['button_text'])
        browse_button.setIcon(browse_icon)
        browse_button.setToolTip("Выбрать папку для сохранения файлов")
        browse_button.clicked.connect(self.browse_folder)

        folder_layout.addWidget(self.folder_input, 3)
        folder_layout.addWidget(browse_button)
        left_layout.addLayout(folder_layout)

        # Добавляем отступ перед кнопками управления
        left_layout.addSpacing(20)

        # Кнопка добавления в очередь с иконкой
        add_button = QPushButton("Добавить в очередь")
        add_icon = qta.icon('fa5s.plus-circle', color=ThemeManager.get_theme()['button_text'])
        add_button.setIcon(add_icon)
        add_button.setIconSize(QSize(16, 16))
        add_button.clicked.connect(self.add_to_queue)
        add_button.setToolTip("Добавить URL в очередь загрузки")
        
        left_layout.addWidget(add_button)

        # Добавляем отступ перед прогресс-баром
        left_layout.addSpacing(15)

        # Прогресс загрузки
        progress_group = QWidget()
        progress_layout = QVBoxLayout(progress_group)
        
        progress_label = QLabel("Прогресс загрузки:")
        progress_layout.addWidget(progress_label)
        
        progress_bar_layout = QHBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        progress_bar_layout.addWidget(self.progress_bar, 3)
        
        self.status_label = QLabel("Готов к загрузке")
        self.status_label.setObjectName("statusLabel")
        progress_bar_layout.addWidget(self.status_label, 1)
        
        progress_layout.addLayout(progress_bar_layout)
        left_layout.addWidget(progress_group)
        
        # Информация о программе и настройки
        info_layout = QHBoxLayout()
        
        about_label = QLabel("© 2025 MaksK")
        about_label.setCursor(Qt.CursorShape.PointingHandCursor)
        about_label.mousePressEvent = self.show_about_dialog
        about_label.setToolTip("Информация о программе")
        
        info_layout.addWidget(about_label)
        info_layout.addStretch()
        
        # Кнопка очистки кэша с иконкой
        clear_cache_button = QPushButton()
        clear_cache_icon = qta.icon('fa5s.trash-alt', color=ThemeManager.get_theme()['button_text'])
        clear_cache_button.setIcon(clear_cache_icon)
        clear_cache_button.setToolTip("Очистить кэш видео")
        clear_cache_button.clicked.connect(self.clear_cache)
        clear_cache_button.setFixedSize(40, 40)
        
        info_layout.addWidget(clear_cache_button)
        
        left_layout.addStretch(2)  # Увеличиваем растягивающийся пробел для лучшего распределения
        left_layout.addLayout(info_layout)
        
        # Правая панель (очередь загрузок)
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)
        
        queue_header_layout = QHBoxLayout()
        queue_label = QLabel("Очередь загрузок")
        queue_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        queue_header_layout.addWidget(queue_label)
        
        right_layout.addLayout(queue_header_layout)
        
        # Список очереди загрузок
        self.queue_list = QListWidget()
        right_layout.addWidget(self.queue_list)
        
        # Кнопки управления очередью
        queue_buttons_layout = QHBoxLayout()
        
        # Кнопка "Загрузить все" с иконкой
        self.start_button = QPushButton("Загрузить все")
        start_icon = qta.icon('fa5s.download', color=ThemeManager.get_theme()['button_text'])
        self.start_button.setIcon(start_icon)
        self.start_button.setIconSize(QSize(16, 16))
        self.start_button.clicked.connect(self.start_downloads)
        self.start_button.setToolTip("Начать загрузку всех файлов в очереди")
        
        # Кнопка "Отменить текущую" с иконкой
        cancel_button = QPushButton("Отменить")
        cancel_icon = qta.icon('fa5s.stop-circle', color=ThemeManager.get_theme()['button_text'])
        cancel_button.setIcon(cancel_icon)
        cancel_button.setIconSize(QSize(16, 16))
        cancel_button.clicked.connect(self.cancel_download)
        cancel_button.setToolTip("Отменить текущую загрузку")
        
        # Кнопка "Удалить выбранное" с иконкой
        remove_button = QPushButton("Удалить")
        remove_icon = qta.icon('fa5s.minus-circle', color=ThemeManager.get_theme()['button_text'])
        remove_button.setIcon(remove_icon)
        remove_button.setIconSize(QSize(16, 16))
        remove_button.clicked.connect(self.remove_selected)
        remove_button.setToolTip("Удалить выбранный элемент из очереди")
        
        # Кнопка "Очистить очередь" с иконкой
        clear_button = QPushButton("Очистить")
        clear_icon = qta.icon('fa5s.trash', color=ThemeManager.get_theme()['button_text'])
        clear_button.setIcon(clear_icon)
        clear_button.setIconSize(QSize(16, 16))
        clear_button.clicked.connect(self.clear_queue)
        clear_button.setToolTip("Очистить всю очередь загрузок")
        
        queue_buttons_layout.addWidget(self.start_button)
        queue_buttons_layout.addWidget(cancel_button)
        queue_buttons_layout.addWidget(remove_button)
        queue_buttons_layout.addWidget(clear_button)
        
        right_layout.addLayout(queue_buttons_layout)
        
        # Добавляем панели в сплиттер
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.right_panel)
        
        # Устанавливаем начальные размеры панелей (40% : 60%)
        self.splitter.setSizes([400, 600])
        
        # Добавляем сплиттер в основной макет
        main_layout.addWidget(self.splitter)
        
        self.setCentralWidget(main_widget)
        
        # Статус-бар
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Готов к работе")
        
        # Применяем темную тему
        ThemeManager.apply_theme(self)
        
        # Включаем возможность принимать перетаскивание файлов
        self.setAcceptDrops(True)

    # Импортируем методы из gui_dark_methods.py
    from gui_dark_methods import (
        apply_theme, dragEnterEvent, dropEvent, load_settings, save_settings,
        add_to_queue, update_queue_display, start_downloads, update_progress,
        on_download_finished, show_download_summary, reset_ui_after_downloads,
        clear_download_history, cancel_download, clear_queue, remove_selected,
        show_about_dialog, show_url_report_dialog, set_controls_enabled,
        on_mode_changed, closeEvent, clear_cache, on_url_changed,
        check_url_for_resolutions, update_resolutions, on_resolution_error,
        browse_folder
    )