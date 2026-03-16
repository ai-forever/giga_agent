import os
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool


@tool
def read_file(file_path: str, length: int = 100, start_position: int = 0) -> str:
    """
    Читает содержимое файла с указанной позиции и длиной.
    
    Args:
        file_path: Путь до файла для чтения
        length: Максимальное количество символов для чтения (по умолчанию 100)
        start_position: Позиция начала чтения в файле (по умолчанию 0)
    
    Returns:
        Содержимое файла в виде строки
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.seek(start_position)
            content = f.read(length)
        return content
    except FileNotFoundError:
        return f"Ошибка: Файл '{file_path}' не найден"
    except PermissionError:
        return f"Ошибка: Нет доступа к файлу '{file_path}'"
    except Exception as e:
        return f"Ошибка при чтении файла: {str(e)}"


@tool
def list_files(directory_path: Optional[str] = None) -> str:
    """
    Получает список файлов в указанной директории или в текущей директории.
    
    Args:
        directory_path: Путь к директории (если None, используется текущая директория)
    
    Returns:
        Список файлов в формате строки
    """
    try:
        if directory_path is None:
            directory_path = os.getcwd()
        
        path = Path(directory_path)
        
        if not path.exists():
            return f"Ошибка: Директория '{directory_path}' не существует"
        
        if not path.is_dir():
            return f"Ошибка: '{directory_path}' не является директорией"
        
        files = []
        for item in path.iterdir():
            if item.is_file():
                files.append(item.name)
        
        if not files:
            return f"Директория '{directory_path}' не содержит файлов"
        
        return f"Файлы в '{directory_path}':\n" + "\n".join(sorted(files))
    
    except PermissionError:
        return f"Ошибка: Нет доступа к директории '{directory_path}'"
    except Exception as e:
        return f"Ошибка при получении списка файлов: {str(e)}"
