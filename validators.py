import re
import os
import json
import logging
from datetime import datetime
from typing import Tuple, Dict, Any, List, Set

logger = logging.getLogger('VideoDownloader')

class URLValidationError(Exception):
    """Ошибка валидации URL"""
    pass


class VideoURL:
    """Класс для работы с URL видео и определения сервиса."""
    
    # Путь к файлу конфигурации паттернов URL
    CONFIG_FILE = "url_patterns.json"
    
    # Константы с паттернами URL для разных сервисов
    URL_PATTERNS = {
        'YouTube': [
            r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$',
            r'^https?://youtu\.be/[\w-]{11}(?:\?\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/shorts/[\w-]{11}(?:\?\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/embed/[\w-]{11}(?:\?\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/playlist\?list=[\w-]+(?:&\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/(?:channel|c|user)/[\w-]+(?:/\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/\S+[\?&]v=[\w-]{11}(?:&\S*)?$',
            r'^https?://music\.youtube\.com/watch\?v=[\w-]{11}(?:&\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/tv#/watch/video/control\?v=[\w-]{11}$',
            r'^https?://music\.youtube\.com/playlist\?list=[\w-]+(?:&\S*)?$',
            r'^https?://(?:www\.)?youtube\.com/clip/[\w-]+(?:\?\S*)?$'
        ],
        'VK': [
            r'^https?://(?:www\.)?vk\.com/video-?\d+_\d+(?:\?\S*)?$',
            r'^https?://(?:www\.)?vkvideo\.ru/video-?\d+_\d+(?:\?\S*)?$',
            r'^https?://(?:www\.)?vk\.com/(?:video|clip)-?\d+(?:_\d+)?(?:\?\S*)?$',
            r'^https?://(?:www\.)?vk\.com/videos-?\d+(?:\?\S*)?$',
            r'^https?://(?:www\.)?vk\.com/\S+$',
            r'^https?://(?:www\.)?vk\.com/clips-?\d+(?:\?\S*)?$',
            r'^https?://(?:m\.)?vk\.com/video(?:_ext)?\.php\?.*oid=(?:-?\d+).*id=\d+.*$',
            r'^https?://(?:www\.)?vk\.com/video_ext\.php\?.*oid=(?:-?\d+).*id=\d+.*$'
        ],
        # Добавим еще несколько сервисов (для краткости)
        'RuTube': [
            r'^https?://(?:www\.)?rutube\.ru/video/[\w-]{32}/?(?:\?\S*)?$',
            r'^https?://(?:www\.)?rutube\.ru/play/embed/[\w-]{32}/?(?:\?\S*)?$',
        ],
        'TikTok': [
            r'^https?://(?:www\.)?tiktok\.com/@[\w\.-]+/video/\d+(?:\?\S*)?$',
            r'^https?://(?:vm|vt)\.tiktok\.com/[\w\.-]+/?(?:\?\S*)?$',
        ],
    }
    
    # Объединенные регулярные выражения для быстрой проверки
    _combined_patterns = {}
    _compiled_patterns = {}
    _patterns_loaded = False
    
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
        if not cls._patterns_loaded:
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
            if not cls._patterns_loaded:
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

# Инициализируем паттерны при импорте
VideoURL.load_patterns_from_config()
VideoURL._init_combined_patterns()
VideoURL._patterns_loaded = True 