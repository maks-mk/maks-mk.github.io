# Продолжение методов для класса VideoDownloaderUI

def add_to_queue(self) -> None:
    """Добавляет текущий URL в очередь загрузок."""
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
            "<p>Приложение для скачивания видео и аудио с различных видеохостингов</p>"
            # текст сокращен для краткости
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