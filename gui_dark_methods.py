"""
Методы для класса VideoDownloaderUI
"""

import os
from PyQt6.QtWidgets import QMessageBox, QPushButton, QApplication
from PyQt6.QtCore import Qt

from utils import load_app_logo
from validators import VideoURL
from downloader import ResolutionWorker


def apply_theme(self) -> None:
    """Применяет темную тему к приложению."""
    from gui_dark import ThemeManager
    ThemeManager.apply_theme(self)
    
def dragEnterEvent(self, event) -> None:
    """Обработчик события начала перетаскивания."""
    mime_data = event.mimeData()
    if mime_data.hasText() or mime_data.hasUrls():
        event.acceptProposedAction()
    
def dropEvent(self, event) -> None:
    """Обработчик события завершения перетаскивания."""
    mime_data = event.mimeData()
    if mime_data.hasText():
        text = mime_data.text()
        self.url_input.setText(text)
        self.check_url_for_resolutions(text)
    elif mime_data.hasUrls():
        url = mime_data.urls()[0].toString()
        self.url_input.setText(url)
        self.check_url_for_resolutions(url)
    event.acceptProposedAction()

def check_url_for_resolutions(self, url: str) -> None:
    """
    Проверяет URL и получает доступные разрешения для видео.
    
    Args:
        url: URL видео для проверки
    """
    import logging
    logger = logging.getLogger('VideoDownloader')
    
    url = url.strip()
    if not url:
        return
        
    # Проверяем, является ли URL валидным
    is_valid, _ = VideoURL.is_valid(url)
    if not is_valid:
        return
        
    # Проверяем, включен ли режим видео (для аудио разрешения не нужны)
    if not self.video_radio.isChecked():
        logger.info("Режим аудио: пропуск получения разрешений")
        return
        
    # Устанавливаем текст статуса
    self.status_label.setText("Получение информации о видео...")
    self.progress_bar.setRange(0, 0)  # Неопределенный прогресс
    
    # Определяем сервис
    service = VideoURL.get_service_name(url)
    self.statusBar.showMessage(f"Получение доступных разрешений с {service}...")
    
    # Временно отключаем кнопку добавления в очередь
    self.set_controls_enabled(False)
    
    # Создаем и запускаем ResolutionWorker
    # Сохраняем ссылку на объект ResolutionWorker как атрибут класса
    if hasattr(self, 'resolution_worker') and self.resolution_worker is not None:
        try:
            # Если предыдущий worker еще работает, отсоединяем его сигналы
            self.resolution_worker.resolutions_found.disconnect()
            self.resolution_worker.error_occurred.disconnect()
            self.resolution_worker.terminate()
            self.resolution_worker.wait(1000)  # Ждем максимум 1 секунду
        except Exception as e:
            logger.error(f"Ошибка при остановке предыдущего потока: {e}")
    
    # Создаем новый поток
    self.resolution_worker = ResolutionWorker(url)
    self.resolution_worker.resolutions_found.connect(self.update_resolutions)
    self.resolution_worker.error_occurred.connect(self.on_resolution_error)
    self.resolution_worker.start()
    logger.info(f"Запущен поиск доступных разрешений для: {url}")

def update_resolutions(self, resolutions: list) -> None:
    """
    Обновляет выпадающий список с доступными разрешениями.
    
    Args:
        resolutions: Список доступных разрешений
    """
    import logging
    logger = logging.getLogger('VideoDownloader')
    
    # Проверяем, что поток еще существует и активен
    if not hasattr(self, 'resolution_worker') or self.resolution_worker is None:
        logger.warning("Получен ответ от несуществующего потока ResolutionWorker")
        return
    
    # Блокируем сигналы комбобокса, чтобы избежать срабатывания событий
    self.resolution_combo.blockSignals(True)
    
    # Запоминаем текущее выбранное разрешение
    current_resolution = self.resolution_combo.currentText()
    
    # Очищаем комбобокс
    self.resolution_combo.clear()
    
    # Заполняем найденными разрешениями
    self.resolution_combo.addItems(resolutions)
    
    # Пытаемся восстановить ранее выбранное разрешение
    if current_resolution in resolutions:
        self.resolution_combo.setCurrentText(current_resolution)
    else:
        # Если прежнего разрешения нет, выбираем наилучшее
        self.resolution_combo.setCurrentIndex(0)
    
    # Разблокируем сигналы
    self.resolution_combo.blockSignals(False)
    
    # Обновляем UI
    self.status_label.setText("Информация о видео получена")
    self.statusBar.showMessage(f"Доступны {len(resolutions)} разрешений")
    self.progress_bar.setRange(0, 100)  # Возвращаем нормальный прогресс-бар
    self.progress_bar.setValue(0)
    
    # Включаем элементы управления
    self.set_controls_enabled(True)
    
    # Освобождаем объект ResolutionWorker
    self.resolution_worker = None
    
    logger.info(f"Получены разрешения: {resolutions}")

def on_resolution_error(self, error_message: str) -> None:
    """
    Обрабатывает ошибку получения разрешений.
    
    Args:
        error_message: Сообщение об ошибке
    """
    import logging
    logger = logging.getLogger('VideoDownloader')
    
    # Проверяем, что поток еще существует и активен
    if not hasattr(self, 'resolution_worker') or self.resolution_worker is None:
        logger.warning("Получена ошибка от несуществующего потока ResolutionWorker")
        return
    
    # Восстанавливаем интерфейс
    self.status_label.setText("Ошибка получения информации")
    self.statusBar.showMessage(error_message)
    self.progress_bar.setRange(0, 100)  # Возвращаем нормальный прогресс-бар
    self.progress_bar.setValue(0)
    
    # Включаем элементы управления
    self.set_controls_enabled(True)
    
    # Освобождаем объект ResolutionWorker
    self.resolution_worker = None
    
    logger.error(f"Ошибка получения разрешений: {error_message}")

def on_url_changed(self) -> None:
    """Обработчик изменения URL в поле ввода."""
    url = self.url_input.text().strip()
    self.check_url_for_resolutions(url)
    
def load_settings(self) -> None:
    """Загружает настройки приложения."""
    from PyQt6.QtCore import QSettings
    settings = QSettings("MaksK", "VideoDownloader")
    
    # Загружаем состояние окна
    if settings.contains("geometry"):
        self.restoreGeometry(settings.value("geometry"))
    if settings.contains("windowState"):
        self.restoreState(settings.value("windowState"))
        
    # Загружаем другие настройки
    resolution = settings.value("resolution", "720p", type=str)
    if resolution in ['1080p', '720p', '480p', '360p', '240p']:
        self.resolution_combo.setCurrentText(resolution)
        
    mode = settings.value("mode", "video", type=str)
    if mode == "audio":
        self.audio_radio.setChecked(True)
    else:
        self.video_radio.setChecked(True)
        
    # Размеры сплиттера
    if settings.contains("splitter_sizes"):
        try:
            # Преобразуем значение в список целых чисел
            sizes_str = settings.value("splitter_sizes")
            if isinstance(sizes_str, str):
                # Если значение строка, пытаемся разобрать её
                sizes = [int(x) for x in sizes_str.strip('[]').split(',') if x.strip().isdigit()]
                if len(sizes) >= 2:  # Убеждаемся, что у нас есть хотя бы 2 значения
                    self.splitter.setSizes(sizes)
            elif isinstance(sizes_str, list) and len(sizes_str) >= 2:
                # Если значение уже список, просто конвертируем в int
                sizes = [int(x) if isinstance(x, (int, str)) and str(x).isdigit() else 0 for x in sizes_str]
                self.splitter.setSizes(sizes)
        except Exception as e:
            import logging
            logger = logging.getLogger('VideoDownloader')
            logger.error(f"Ошибка при установке размеров сплиттера: {e}")
            # Устанавливаем размеры по умолчанию
            self.splitter.setSizes([400, 600])

def save_settings(self) -> None:
    """Сохраняет настройки приложения."""
    from PyQt6.QtCore import QSettings
    settings = QSettings("MaksK", "VideoDownloader")
    settings.setValue("geometry", self.saveGeometry())
    settings.setValue("windowState", self.saveState())
    
    # Сохраняем настройки загрузки
    resolution = self.resolution_combo.currentText()
    settings.setValue("resolution", resolution)
    
    mode = "audio" if self.audio_radio.isChecked() else "video"
    settings.setValue("mode", mode)
    
    # Сохраняем размеры сплиттера
    try:
        splitter_sizes = self.splitter.sizes()
        # Сохраняем как список целых чисел
        settings.setValue("splitter_sizes", splitter_sizes)
    except Exception as e:
        import logging
        logger = logging.getLogger('VideoDownloader')
        logger.error(f"Ошибка при сохранении размеров сплиттера: {e}")

def add_to_queue(self) -> None:
    """Добавляет текущий URL в очередь загрузок."""
    url: str = self.url_input.text().strip()
    
    if not url:
        QMessageBox.warning(self, "Ошибка", "Введите URL видео")
        return
        
    # Проверяем, является ли URL валидным
    is_valid, error_message = VideoURL.is_valid(url)
    if not is_valid:
        QMessageBox.warning(self, "Ошибка", f"Некорректный URL: {error_message}")
        return
        
    mode: str = "video" if self.video_radio.isChecked() else "audio"
    resolution: str = self.resolution_combo.currentText() if mode == "video" else None

    if self.download_manager.add_to_queue(url, mode, resolution):
        self.update_queue_display()
        self.url_input.clear()
        self.save_settings()
        self.status_label.setText("Видео добавлено в очередь")
    else:
        QMessageBox.warning(self, "Ошибка", "Не удалось добавить видео в очередь")

def update_queue_display(self) -> None:
    """Обновляет отображение очереди загрузок."""
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
    """Запускает процесс загрузки файлов из очереди."""
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
    """
    Обновляет отображение прогресса загрузки.
    
    Args:
        status: Текстовый статус загрузки
        percent: Процент завершения загрузки
    """
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
    """
    Обработчик завершения загрузки.
    
    Args:
        success: Флаг успешной загрузки
        message: Сообщение о результате
        filename: Имя загруженного файла
    """
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
    """Показывает сводку о результатах загрузок."""
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
    import logging
    logger = logging.getLogger('VideoDownloader')
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
    """Отменяет текущую загрузку."""
    self.download_manager.cancel_current_download()
    self.status_label.setText("Загрузка отменяется...")
    self.status_label.setStyleSheet("color: orange;")
    self.progress_bar.setValue(0)
    self.progress_bar.setRange(0, 100)

def clear_queue(self) -> None:
    """Очищает очередь загрузок."""
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
    """Удаляет выбранный элемент из очереди загрузок."""
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
            "<h2 style='text-align: center;'>Video/Audio Downloader by MaksK v1.098</h2>"
            "<p>Приложение для скачивания видео и аудио с различных видеохостингов</p>"
            "<ul>"
            "<li>YouTube и YouTube Music</li>"
            "<li>VK (ВКонтакте)</li>" 
            "<li>RuTube</li>"
            "<li>И множество других (более 100 сайтов)</li>"
            "</ul>"
        )
    else:
        about_text = (
            "<div style='text-align: center;'><span style='font-size: 80px; color: red;'>!</span></div>"
            "<h2 style='text-align: center;'>Video/Audio Downloader v1.098</h2>"
            "<p>Приложение для скачивания видео и аудио с различных видеохостингов</p>"
        )
    
    msg_box = QMessageBox(self)
    msg_box.setWindowTitle("О программе")
    msg_box.setTextFormat(Qt.TextFormat.RichText)
    msg_box.setText(about_text)
    
    # Добавляем кнопки
    report_btn = QPushButton("Сообщить о новом формате URL")
    report_btn.clicked.connect(self.show_url_report_dialog)
    
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
    # Сокращенная версия для краткости
    dialog = QMessageBox(self)
    dialog.setWindowTitle("Сообщить о новом формате URL")
    dialog.setIcon(QMessageBox.Icon.Information)
    dialog.setText("Если вы обнаружили URL видео, который не распознается программой, "
                  "вы можете отправить его разработчику для добавления поддержки.")
    dialog.addButton(QMessageBox.StandardButton.Ok)
    dialog.exec()

def set_controls_enabled(self, enabled: bool) -> None:
    """
    Включает или отключает элементы управления.
    
    Args:
        enabled: True для включения, False для отключения
    """
    self.url_input.setEnabled(enabled)
    self.video_radio.setEnabled(enabled)
    self.audio_radio.setEnabled(enabled)
    self.resolution_combo.setEnabled(enabled)
    # Кнопка "Загрузить все" управляется отдельно для более точного контроля

def on_mode_changed(self) -> None:
    """Обработчик изменения режима загрузки (видео/аудио)."""
    is_video: bool = self.video_radio.isChecked()
    self.resolution_combo.setVisible(is_video)
    resolution_label = self.resolution_layout.itemAt(0).widget()
    if resolution_label:
        resolution_label.setVisible(is_video)
        
    # Если переключились на видео-режим и есть URL, получаем разрешения
    if is_video and self.url_input.text().strip():
        self.check_url_for_resolutions(self.url_input.text().strip())

def closeEvent(self, event):
    """Обработчик закрытия приложения."""
    from downloader import video_info_cache
    import logging
    
    logger = logging.getLogger('VideoDownloader')
    logger.info("Завершение работы приложения...")
    
    # Останавливаем активные потоки
    if hasattr(self, 'resolution_worker') and self.resolution_worker is not None:
        try:
            logger.info("Остановка потока ResolutionWorker...")
            self.resolution_worker.terminate()
            self.resolution_worker.wait(2000)  # Ждем максимум 2 секунды
        except Exception as e:
            logger.error(f"Ошибка при остановке потока ResolutionWorker: {e}")
            
    # Отменяем текущую загрузку, если есть
    if self.download_manager.current_download:
        logger.info("Отмена текущей загрузки...")
        self.download_manager.cancel_current_download()
        
    # Ждем завершения всех потоков в пуле
    self.thread_pool.waitForDone(3000)  # Ждем максимум 3 секунды
    
    # Сохраняем кэш при выходе
    video_info_cache.save_to_file()
    
    # Сохраняем настройки
    self.save_settings()
    
    logger.info("Приложение успешно завершено")
    event.accept()

def clear_cache(self) -> None:
    """Очищает кэш информации о видео."""
    from downloader import video_info_cache
    video_info_cache.clear()
    video_info_cache.save_to_file()
    QMessageBox.information(self, "Кэш очищен", 
                         "Кэш информации о видео успешно очищен.") 