# utils.py
import os
import re
import unicodedata
import logging
import shutil
from urllib.parse import quote

logger = logging.getLogger(__name__)

def safe_folder_name(name: str) -> str:
    """Преобразует строку в безопасное имя папки"""
    if not name:
        return "unnamed"
    name = unicodedata.normalize('NFKD', name)
    name = re.sub(r'[^\w\s-]', '', name, flags=re.UNICODE)
    name = re.sub(r'[-\s]+', '_', name, flags=re.UNICODE).strip('-_')
    return name[:255] if name else "unnamed"

def cleanup_album_thumbnails(album_name, thumbnail_folder):
    """Очищает все превью для указанного альбома"""
    try:
        album_thumb_path = os.path.join(thumbnail_folder, album_name)
        if os.path.exists(album_thumb_path):
            shutil.rmtree(album_thumb_path)
            logger.info(f"Cleaned up thumbnails for album: {album_name}")
        else:
            logger.info(f"No thumbnails found for album: {album_name}")
    except Exception as e:
        logger.error(f"Error cleaning up thumbnails for album {album_name}: {e}")

def cleanup_empty_folders(folder_path):
    """Рекурсивно удаляет пустые папки"""
    try:
        for root, dirs, files in os.walk(folder_path, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):  # Папка пуста
                        os.rmdir(dir_path)
                        logger.debug(f"Removed empty folder: {dir_path}")
                except OSError:
                    pass  # Папка не пуста или нет прав
    except Exception as e:
        logger.error(f"Error cleaning up empty folders in {folder_path}: {e}")

def cleanup_file_thumbnails(filename, upload_folder, thumbnail_folder):
    """Очищает превью для конкретного файла"""
    try:
        original_path = os.path.join(upload_folder, filename)
        if not os.path.exists(original_path):
            # Если оригинального файла нет, ищем и удаляем все возможные превью
            rel_dir = os.path.dirname(filename)
            file_base = os.path.splitext(os.path.basename(filename))[0]

            if rel_dir and rel_dir != '.':
                thumb_dir = os.path.join(thumbnail_folder, rel_dir)
                if os.path.exists(thumb_dir):
                    # Удаляем все превью для этого файла
                    for thumb_file in os.listdir(thumb_dir):
                        if thumb_file.startswith(file_base + '_'):
                            thumb_path = os.path.join(thumb_dir, thumb_file)
                            os.remove(thumb_path)
                            logger.info(f"Deleted orphaned thumbnail: {thumb_path}")
        else:
            # Удаляем превью для существующего файла
            # Для этого нужно обновить get_thumbnail_path чтобы принимать параметры
            # Временно оставляем как есть, можно доработать позже
            pass

    except Exception as e:
        logger.error(f"Error cleaning up thumbnails for file {filename}: {e}")
