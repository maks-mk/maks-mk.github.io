#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль оптимизации для Video Downloader.
Содержит утилиты для мониторинга производительности и управления ресурсами.
"""

import time
import logging
import threading
from typing import Dict, Any, Optional, Callable
from functools import wraps
import psutil
import gc

logger = logging.getLogger('VideoDownloader')


class PerformanceProfiler:
    """Профайлер для измерения производительности функций."""
    
    def __init__(self):
        self.stats = {}
        self.lock = threading.Lock()
    
    def profile(self, func_name: str = None):
        """Декоратор для профилирования функций."""
        def decorator(func):
            name = func_name or f"{func.__module__}.{func.__name__}"
            
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                start_memory = psutil.Process().memory_info().rss
                
                try:
                    result = func(*args, **kwargs)
                    success = True
                    error = None
                except Exception as e:
                    result = None
                    success = False
                    error = str(e)
                    raise
                finally:
                    end_time = time.time()
                    end_memory = psutil.Process().memory_info().rss
                    
                    execution_time = end_time - start_time
                    memory_delta = end_memory - start_memory
                    
                    with self.lock:
                        if name not in self.stats:
                            self.stats[name] = {
                                'calls': 0,
                                'total_time': 0,
                                'avg_time': 0,
                                'max_time': 0,
                                'min_time': float('inf'),
                                'total_memory_delta': 0,
                                'avg_memory_delta': 0,
                                'errors': 0
                            }
                        
                        stats = self.stats[name]
                        stats['calls'] += 1
                        stats['total_time'] += execution_time
                        stats['avg_time'] = stats['total_time'] / stats['calls']
                        stats['max_time'] = max(stats['max_time'], execution_time)
                        stats['min_time'] = min(stats['min_time'], execution_time)
                        stats['total_memory_delta'] += memory_delta
                        stats['avg_memory_delta'] = stats['total_memory_delta'] / stats['calls']
                        
                        if not success:
                            stats['errors'] += 1
                        
                        # Логируем медленные операции
                        if execution_time > 1.0:  # Больше 1 секунды
                            logger.warning(f"Медленная операция {name}: {execution_time:.2f}с")
                
                return result
            return wrapper
        return decorator
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику производительности."""
        with self.lock:
            return dict(self.stats)
    
    def reset_stats(self):
        """Сбрасывает статистику."""
        with self.lock:
            self.stats.clear()
    
    def log_stats(self):
        """Логирует статистику производительности."""
        with self.lock:
            if not self.stats:
                logger.info("Статистика производительности пуста")
                return
            
            logger.info("=== Статистика производительности ===")
            for name, stats in sorted(self.stats.items()):
                logger.info(
                    f"{name}: "
                    f"вызовов={stats['calls']}, "
                    f"среднее время={stats['avg_time']:.3f}с, "
                    f"макс время={stats['max_time']:.3f}с, "
                    f"средняя память={stats['avg_memory_delta']/(1024*1024):.1f}МБ, "
                    f"ошибок={stats['errors']}"
                )


class ResourceManager:
    """Менеджер ресурсов для контроля использования системных ресурсов."""
    
    def __init__(self, max_memory_mb: int = 1024, max_cpu_percent: float = 80.0):
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.max_cpu_percent = max_cpu_percent
        self.process = psutil.Process()
        self.monitoring = False
        self.monitor_thread = None
        self.callbacks = {
            'memory_limit': [],
            'cpu_limit': [],
            'resource_warning': []
        }
    
    def add_callback(self, event_type: str, callback: Callable):
        """Добавляет callback для событий ресурсов."""
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
    
    def start_monitoring(self, interval: float = 5.0):
        """Запускает мониторинг ресурсов."""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True
        )
        self.monitor_thread.start()
        logger.info("Мониторинг ресурсов запущен")
    
    def stop_monitoring(self):
        """Останавливает мониторинг ресурсов."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1.0)
        logger.info("Мониторинг ресурсов остановлен")
    
    def _monitor_loop(self, interval: float):
        """Основной цикл мониторинга."""
        while self.monitoring:
            try:
                # Проверяем память
                memory_usage = self.process.memory_info().rss
                if memory_usage > self.max_memory_bytes:
                    logger.warning(f"Превышен лимит памяти: {memory_usage/(1024*1024):.1f}МБ")
                    for callback in self.callbacks['memory_limit']:
                        try:
                            callback(memory_usage)
                        except Exception as e:
                            logger.error(f"Ошибка в callback памяти: {e}")
                
                # Проверяем CPU
                cpu_percent = self.process.cpu_percent()
                if cpu_percent > self.max_cpu_percent:
                    logger.warning(f"Превышен лимит CPU: {cpu_percent:.1f}%")
                    for callback in self.callbacks['cpu_limit']:
                        try:
                            callback(cpu_percent)
                        except Exception as e:
                            logger.error(f"Ошибка в callback CPU: {e}")
                
                # Общие предупреждения о ресурсах
                if memory_usage > self.max_memory_bytes * 0.8 or cpu_percent > self.max_cpu_percent * 0.8:
                    for callback in self.callbacks['resource_warning']:
                        try:
                            callback({
                                'memory_mb': memory_usage / (1024 * 1024),
                                'cpu_percent': cpu_percent
                            })
                        except Exception as e:
                            logger.error(f"Ошибка в callback предупреждения: {e}")
                
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Ошибка в мониторинге ресурсов: {e}")
                time.sleep(interval)
    
    def get_resource_info(self) -> Dict[str, Any]:
        """Возвращает информацию о текущем использовании ресурсов."""
        try:
            memory_info = self.process.memory_info()
            return {
                'memory_mb': memory_info.rss / (1024 * 1024),
                'memory_percent': self.process.memory_percent(),
                'cpu_percent': self.process.cpu_percent(),
                'num_threads': self.process.num_threads(),
                'num_fds': getattr(self.process, 'num_fds', lambda: 0)(),  # Linux/macOS only
            }
        except Exception as e:
            logger.error(f"Ошибка получения информации о ресурсах: {e}")
            return {}
    
    def force_cleanup(self):
        """Принудительная очистка ресурсов."""
        logger.info("Принудительная очистка ресурсов...")
        
        # Сборка мусора
        collected = gc.collect()
        logger.info(f"Собрано {collected} объектов сборщиком мусора")
        
        # Дополнительная очистка
        try:
            import ctypes
            if hasattr(ctypes, 'windll'):  # Windows
                ctypes.windll.kernel32.SetProcessWorkingSetSize(-1, -1, -1)
        except Exception:
            pass


# Глобальные экземпляры
performance_profiler = PerformanceProfiler()
resource_manager = ResourceManager(max_memory_mb=1024, max_cpu_percent=80.0)


def optimize_for_large_files():
    """Применяет оптимизации для работы с большими файлами."""
    logger.info("Применение оптимизаций для больших файлов...")
    
    # Запускаем мониторинг ресурсов
    resource_manager.start_monitoring(interval=10.0)
    
    # Добавляем callback для автоматической очистки памяти
    def memory_cleanup_callback(memory_usage):
        logger.warning("Автоматическая очистка памяти из-за превышения лимита")
        resource_manager.force_cleanup()
    
    resource_manager.add_callback('memory_limit', memory_cleanup_callback)
    
    logger.info("Оптимизации для больших файлов применены")


def get_optimization_stats() -> Dict[str, Any]:
    """Возвращает статистику оптимизации."""
    return {
        'performance': performance_profiler.get_stats(),
        'resources': resource_manager.get_resource_info()
    }
