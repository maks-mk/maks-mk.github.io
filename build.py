import os
import sys
import shutil
import subprocess
from typing import List, Tuple

def install_requirements() -> None:
    """Устанавливает необходимые пакеты"""
    requirements = [
        'pyinstaller',
        'PyQt6',
        'yt-dlp',
        'Pillow',
        'requests',
        'packaging',
        'qtawesome',
        'psutil'
    ]
    
    print("Проверка и установка необходимых пакетов...")
    for package in requirements:
        try:
            __import__(package.replace('-', '_'))
            print(f"✓ {package} уже установлен")
        except ImportError:
            print(f"Установка {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def get_project_files() -> List[str]:
    """Возвращает список файлов проекта"""
    # Основные модули
    modules = [
        'main.py',
        'gui_dark.py',
        'gui_dark_methods.py',
        'downloader.py',
        'validators.py',
        'utils.py',
        'optimizations.py',
        'yt_dlp_utils.py'  # Добавлен новый модуль
    ]

    # Ресурсы
    resources = [
        'vid1.png',
        'vid1.ico',
        'url_patterns.json',
        'requirements.txt'
    ]

    return modules + resources

def check_requirements() -> Tuple[bool, str]:
    """Проверяет наличие необходимых зависимостей"""
    try:
        import PyQt6  # noqa: F401
        import yt_dlp  # noqa: F401
        import PIL  # noqa: F401
        import requests  # noqa: F401
        import packaging  # noqa: F401
        import qtawesome  # noqa: F401
        import psutil  # noqa: F401
        # Используем subprocess для проверки pyinstaller
        subprocess.run(['pyinstaller', '--version'],
                      stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE,
                      check=True)
        return True, ""
    except ImportError as e:
        return False, f"Отсутствует необходимый пакет: {str(e)}"
    except subprocess.CalledProcessError:
        return False, "PyInstaller не установлен или не доступен"
    except Exception as e:
        return False, f"Неизвестная ошибка: {str(e)}"

def cleanup_build_dirs() -> None:
    """Очищает директории сборки"""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"Очищена директория: {dir_name}")

def build_exe() -> bool:
    """Выполняет сборку exe файла"""
    try:
        # Проверка зависимостей
        requirements_ok, error_msg = check_requirements()
        if not requirements_ok:
            print(f"Ошибка: {error_msg}")
            print("Попытка установить необходимые пакеты...")
            install_requirements()
            # Повторная проверка после установки
            requirements_ok, error_msg = check_requirements()
            if not requirements_ok:
                print(f"Ошибка после попытки установки: {error_msg}")
                return False

        # Очистка директорий сборки
        cleanup_build_dirs()

        # Проверка наличия необходимых файлов
        required_files = get_project_files()
        missing_files = [f for f in required_files if not os.path.exists(f)]
        if missing_files:
            print(f"Ошибка: Следующие необходимые файлы не найдены: {', '.join(missing_files)}")
            return False
        
        # Создадим пустые директории для сохранения
        os.makedirs('dist/downloads', exist_ok=True)
        os.makedirs('dist/logs', exist_ok=True)

        # Запуск PyInstaller с указанными параметрами
        datas = [
            # Основные ресурсы
            'vid1.png;.',
            'vid1.ico;.',
            'url_patterns.json;.',
            # Внешние инструменты (если есть)
        ]

        # Добавляем FFmpeg файлы если они есть
        if os.path.exists('ffmpeg.exe'):
            datas.append('ffmpeg.exe;.')
        if os.path.exists('ffprobe.exe'):
            datas.append('ffprobe.exe;.')
        
        cmd = [
            'pyinstaller',
            '--noconfirm',
            '--onefile',
            '--windowed',
            '--icon', 'vid1.ico',
            '--clean',
            '--name', 'VideoDownloader',
            # Основной скрипт - теперь main.py
            'main.py'
        ]
        
        # Добавляем все дополнительные данные
        for data in datas:
            cmd.extend(['--add-data', data])
        
        subprocess.run(cmd, check=True)

        # Проверка результата сборки
        exe_path = os.path.join('dist', 'VideoDownloader.exe')
        if os.path.exists(exe_path):
            print(f"\nСборка успешно завершена!")
            print(f"Исполняемый файл создан: {exe_path}")
            return True
        else:
            print("\nОшибка: Файл exe не найден после сборки")
            return False

    except subprocess.CalledProcessError as e:
        print(f"\nОшибка при выполнении команды PyInstaller: {e}")
        return False
    except Exception as e:
        print(f"\nНеожиданная ошибка при сборке: {e}")
        return False

def main() -> None:
    """Основная функция сборки"""
    print("Начало сборки VideoDownloader...")
    
    # Проверяем наличие необходимых файлов
    required_files = get_project_files()
    missing_files = [f for f in required_files if not os.path.exists(f)]
    if missing_files:
        print(f"Ошибка: Следующие необходимые файлы не найдены: {', '.join(missing_files)}")
        sys.exit(1)
        
    # Проверяем наличие дополнительных необходимых файлов
    additional_files = ['ffmpeg.exe', 'ffprobe.exe']
    missing_additional = [f for f in additional_files if not os.path.exists(f)]
    if missing_additional:
        print(f"Предупреждение: Следующие дополнительные файлы не найдены: {', '.join(missing_additional)}")
        print("Эти файлы необходимы для работы с видео. Убедитесь, что они будут доступны при запуске программы.")

    if build_exe():
        print("\nПроцесс сборки успешно завершен!")
        print("\nРекомендации после сборки:")
        print("1. Создайте папки 'downloads' и 'logs' в директории с исполняемым файлом")
        print("2. Убедитесь, что файлы ffmpeg.exe и ffprobe.exe находятся рядом с исполняемым файлом")
    else:
        print("\nПроцесс сборки завершился с ошибками")
        sys.exit(1)

if __name__ == '__main__':
    main() 