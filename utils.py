# utils.py
import os
import re
import unicodedata
import logging
import shutil
import json
from urllib.parse import quote
from database import db_manager

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


def log_user_action(action, resource_type=None, resource_name=None, details=None, user=None):
    """
    Записывает действие пользователя в базу данных.

    :param action: str - Тип действия (например, 'upload', 'delete_album', 'delete_article', 'login', 'logout')
    :param resource_type: str - Тип ресурса ('file', 'album', 'article', 'user')
    :param resource_name: str - Имя ресурса
    :param details: dict - Дополнительные детали (будет сериализовано в JSON)
    :param user: dict - Объект пользователя (если None, будет использован текущий пользователь из сессии)
    """
    if user is None:
        from auth_system import get_current_user
        user = get_current_user()

    if not user:
        # Если пользователь не аутентифицирован, логируем как анонимное действие
        user_id = 'anonymous'
        username = 'anonymous'
    else:
        user_id = user.get('sub')  # Используем уникальный идентификатор пользователя из OIDC
        username = user.get('name', user.get('preferred_username', 'unknown_user'))

    details_json = json.dumps(details) if details else None

    query = """
    INSERT INTO user_actions_log (user_id, username, action, resource_type, resource_name, details)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        db_manager.execute_query(query, (user_id, username, action, resource_type, resource_name, details_json),
                                 commit=True)
        logger.info(
            f"Logged action '{action}' for user '{username}' on {resource_type or 'N/A'} '{resource_name or 'N/A'}'")
    except Exception as e:
        logger.error(f"Failed to log action '{action}' for user '{username}': {e}")


def log_user_login(user_info, login_method='oauth'):
    """
    Специальная функция для логирования успешного входа пользователя

    :param user_info: dict - Информация о пользователе
    :param login_method: str - Метод входа ('oauth', 'form', etc.)
    """
    user_id = user_info.get('sub')
    username = user_info.get('preferred_username', user_info.get('email', 'unknown_user'))

    details = {
        'login_method': login_method,
        'user_agent': request.headers.get('User-Agent', 'Unknown') if 'request' in globals() else 'Unknown',
        'ip_address': request.remote_addr if 'request' in globals() and hasattr(request, 'remote_addr') else 'Unknown',
        'roles': user_info.get('roles', []),
        'display_roles': user_info.get('display_roles', [])
    }

    log_user_action(
        action='login',
        resource_type='user',
        resource_name=username,
        details=details,
        user=user_info
    )


def log_user_logout(user_info):
    """
    Специальная функция для логирования выхода пользователя

    :param user_info: dict - Информация о пользователе
    """
    user_id = user_info.get('sub')
    username = user_info.get('preferred_username', user_info.get('email', 'unknown_user'))

    log_user_action(
        action='logout',
        resource_type='user',
        resource_name=username,
        user=user_info
    )
