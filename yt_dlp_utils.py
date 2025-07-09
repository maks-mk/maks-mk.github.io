#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Дополнительные утилиты для работы с yt-dlp
Автор: MaksK
"""

import os
import sys
import logging
import json
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

import yt_dlp

logger = logging.getLogger('VideoDownloader')


class YtDlpConfigManager:
    """Менеджер конфигурации yt-dlp"""
    
    def __init__(self):
        self.config_dir = Path.home() / '.config' / 'yt-dlp'
        self.config_file = self.config_dir / 'config.json'
        self.ensure_config_dir()
    
    def ensure_config_dir(self) -> None:
        """Создает директорию конфигурации если её нет"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """
        Сохраняет конфигурацию в файл.
        
        Args:
            config: Словарь с настройками
            
        Returns:
            True при успешном сохранении
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.exception(f"Ошибка сохранения конфигурации: {e}")
            return False
    
    def load_config(self) -> Dict[str, Any]:
        """
        Загружает конфигурацию из файла.
        
        Returns:
            Словарь с настройками
        """
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.exception(f"Ошибка загрузки конфигурации: {e}")
        
        return self.get_default_config()
    
    def get_default_config(self) -> Dict[str, Any]:
        """
        Возвращает конфигурацию по умолчанию.
        
        Returns:
            Словарь с настройками по умолчанию
        """
        return {
            'preferred_quality': '1080p',
            'preferred_codec': 'h264',
            'audio_quality': '320',
            'use_cookies': True,
            'geo_bypass': True,
            'max_retries': 10,
            'timeout': 30,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'output_template': '%(title)s_%(height)sp.%(ext)s'
        }


class YtDlpFormatAnalyzer:
    """Анализатор форматов yt-dlp"""
    
    @staticmethod
    def analyze_formats(formats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Анализирует доступные форматы.
        
        Args:
            formats: Список форматов от yt-dlp
            
        Returns:
            Словарь с анализом форматов
        """
        if not formats:
            return {'error': 'Форматы не найдены'}
        
        analysis = {
            'total_formats': len(formats),
            'video_formats': [],
            'audio_formats': [],
            'combined_formats': [],
            'resolutions': set(),
            'codecs': {'video': set(), 'audio': set()},
            'best_quality': None,
            'recommended': None
        }
        
        for fmt in formats:
            # Классификация форматов
            has_video = fmt.get('vcodec') != 'none' and fmt.get('height')
            has_audio = fmt.get('acodec') != 'none'
            
            if has_video and has_audio:
                analysis['combined_formats'].append(fmt)
            elif has_video:
                analysis['video_formats'].append(fmt)
                analysis['resolutions'].add(fmt.get('height'))
                if fmt.get('vcodec'):
                    analysis['codecs']['video'].add(fmt.get('vcodec'))
            elif has_audio:
                analysis['audio_formats'].append(fmt)
                if fmt.get('acodec'):
                    analysis['codecs']['audio'].add(fmt.get('acodec'))
        
        # Преобразуем sets в lists для JSON сериализации
        analysis['resolutions'] = sorted(list(analysis['resolutions']), reverse=True)
        analysis['codecs']['video'] = list(analysis['codecs']['video'])
        analysis['codecs']['audio'] = list(analysis['codecs']['audio'])
        
        # Находим лучшее качество
        analysis['best_quality'] = YtDlpFormatAnalyzer._find_best_format(formats)
        analysis['recommended'] = YtDlpFormatAnalyzer._find_recommended_format(formats)
        
        return analysis
    
    @staticmethod
    def _find_best_format(formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Находит формат с лучшим качеством"""
        if not formats:
            return None
        
        # Сортируем по качеству
        def quality_score(fmt):
            height = fmt.get('height', 0) or 0
            tbr = fmt.get('tbr', 0) or 0
            fps = fmt.get('fps', 0) or 0
            
            # Бонус за современные кодеки
            vcodec = fmt.get('vcodec', '').lower()
            codec_bonus = 0
            if 'av01' in vcodec:
                codec_bonus = 1000
            elif 'vp9' in vcodec:
                codec_bonus = 500
            elif 'h264' in vcodec or 'avc1' in vcodec:
                codec_bonus = 100
            
            return height * 10 + tbr + fps + codec_bonus
        
        return max(formats, key=quality_score)
    
    @staticmethod
    def _find_recommended_format(formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Находит рекомендуемый формат (баланс качества и размера)"""
        if not formats:
            return None
        
        # Ищем 1080p или ближайшее к нему
        target_height = 1080
        suitable_formats = [
            fmt for fmt in formats 
            if fmt.get('height') and fmt.get('vcodec') != 'none'
        ]
        
        if not suitable_formats:
            return None
        
        # Находим ближайший к целевому разрешению
        def distance_score(fmt):
            height = fmt.get('height', 0)
            return abs(height - target_height)
        
        return min(suitable_formats, key=distance_score)


class YtDlpDiagnostics:
    """Диагностика проблем с yt-dlp"""
    
    @staticmethod
    def run_diagnostics(url: str) -> Dict[str, Any]:
        """
        Запускает диагностику для URL.
        
        Args:
            url: URL для диагностики
            
        Returns:
            Результаты диагностики
        """
        import datetime
        results = {
            'url': url,
            'timestamp': str(datetime.datetime.now()),
            'tests': {}
        }
        
        # Тест 1: Базовое извлечение информации
        results['tests']['basic_extraction'] = YtDlpDiagnostics._test_basic_extraction(url)
        
        # Тест 2: Проверка форматов
        results['tests']['formats_check'] = YtDlpDiagnostics._test_formats(url)
        
        # Тест 3: Проверка сети
        results['tests']['network_check'] = YtDlpDiagnostics._test_network(url)
        
        return results
    
    @staticmethod
    def _test_basic_extraction(url: str) -> Dict[str, Any]:
        """Тестирует базовое извлечение информации"""
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'status': 'success',
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown')
                }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    @staticmethod
    def _test_formats(url: str) -> Dict[str, Any]:
        """Тестирует доступность форматов"""
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'listformats': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                return {
                    'status': 'success',
                    'formats_count': len(formats),
                    'has_video': any(f.get('vcodec') != 'none' for f in formats),
                    'has_audio': any(f.get('acodec') != 'none' for f in formats)
                }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
    
    @staticmethod
    def _test_network(url: str) -> Dict[str, Any]:
        """Тестирует сетевое подключение"""
        try:
            import urllib.request
            import urllib.parse
            
            # Извлекаем домен из URL
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc
            
            # Простая проверка доступности
            test_url = f"https://{domain}"
            req = urllib.request.Request(test_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                return {
                    'status': 'success',
                    'domain': domain,
                    'response_code': response.getcode()
                }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
