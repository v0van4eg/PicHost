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
    name = re.sub(r'[^\w\s\.-]', '', name, flags=re.UNICODE)
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


def get_client_info():
    """
    Получает информацию о клиенте из текущего запроса
    """
    try:
        from flask import request
        client_ip = request.environ.get('HTTP_X_REAL_IP',
                                        request.environ.get('HTTP_X_FORWARDED_FOR',
                                                            request.remote_addr))

        # Если IP представляет собой список (когда несколько прокси), берем первый
        if ',' in client_ip:
            client_ip = client_ip.split(',')[0].strip()

        user_agent = request.headers.get('User-Agent', 'Unknown')

        return {
            'ip_address': client_ip
            # 'full_name': "Фамилия Имя"
        }

    except Exception as e:
        logger.error(f"Error getting client info: {e}")
        return {
            'ip_address': 'Unknown',
            'user_agent': 'Unknown'
        }


# utils.py - исправленные функции логирования

# utils.py - обновить log_user_login

def log_user_login(user_info, login_method='oauth'):
    """
    Специальная функция для логирования успешного входа пользователя
    """
    user_id = user_info.get('sub')
    username = user_info.get('preferred_username', user_info.get('email', 'unknown_user'))

    # Получаем полное имя пользователя
    given_name = user_info.get('given_name', '')
    family_name = user_info.get('family_name', '')
    full_name = f"{given_name} {family_name}".strip()
    display_name = full_name if full_name else username

    details = {
        'ip_address': get_client_info().get('ip_address', 'Unknown'),
        'email': user_info.get('email', ''),
        'given_name': given_name,
        'family_name': family_name,
        'has_default_role': user_info.get('has_default_role', False),
        'user_roles': user_info.get('user_roles', [])
    }

    log_user_action(
        action='login',
        resource_type='user',
        resource_name=display_name,
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

    # Получаем полное имя пользователя
    given_name = user_info.get('given_name', '')
    family_name = user_info.get('family_name', '')
    full_name = f"{given_name} {family_name}".strip()
    display_name = full_name if full_name else username

    details = {
        'ip_address': get_client_info().get('ip_address', 'Unknown'),
        'email': user_info.get('email', ''),
        'given_name': given_name,
        'family_name': family_name
    }

    log_user_action(
        action='logout',
        resource_type='user',
        resource_name=display_name,
        details=details,
        user=user_info
    )


# utils.py (добавьте новую функцию)

def log_auto_logout(user_info, reason='session_timeout'):
    """
    Логирует автоматический выход пользователя по таймауту

    :param user_info: dict - Информация о пользователе
    :param reason: str - Причина автоматического выхода
    """
    username = user_info.get('preferred_username', user_info.get('email', 'unknown_user'))

    # Получаем полное имя пользователя
    given_name = user_info.get('given_name', '')
    family_name = user_info.get('family_name', '')
    full_name = f"{given_name} {family_name}".strip()
    display_name = full_name if full_name else username

    details = {
        'ip_address': get_client_info().get('ip_address', 'Unknown'),
        'reason': reason,
        'email': user_info.get('email', ''),
        'given_name': given_name,
        'family_name': family_name
    }

    log_user_action(
        action='auto_logout',
        resource_type='user',
        resource_name=display_name,
        details=details,
        user=user_info
    )


def log_user_action(action, resource_type=None, resource_name=None, details=None, user=None, request_info=None):
    """
    Записывает действие пользователя в базу данных.

    :param action: str - Тип действия (например, 'upload', 'delete_album', 'delete_article', 'login', 'logout')
    :param resource_type: str - Тип ресурса ('file', 'album', 'article', 'user')
    :param resource_name: str - Имя ресурса
    :param details: dict - Дополнительные детали (будет сериализовано в JSON)
    :param user: dict - Объект пользователя (если None, будет использован текущий пользователь из сессии)
    :param request_info: dict - Информация о запросе (если None, будет получена автоматически)
    """
    if user is None:
        from auth_system import get_current_user
        user = get_current_user()

    if not user:
        # Если пользователь не аутентифицирован, логируем как анонимное действие
        user_id = 'anonymous'
        username = 'anonymous'
        display_name = 'Анонимный пользователь'
    else:
        user_id = user.get('sub')  # Используем уникальный идентификатор пользователя из OIDC
        username = user.get('name', user.get('preferred_username', 'unknown_user'))

        # Формируем отображаемое имя
        given_name = user.get('given_name', '')
        family_name = user.get('family_name', '')
        full_name = f"{given_name} {family_name}".strip()
        display_name = full_name if full_name else username

    # Получаем информацию о клиенте, если не предоставлена
    if request_info is None:
        request_info = get_client_info()

    # Объединяем детали с информацией о запросе
    if details is None:
        details = {}

    # Убедимся, что IP адрес всегда включен в детали
    if 'ip_address' not in details:
        details['ip_address'] = request_info.get('ip_address', 'Unknown')

    # Используем json.dumps с ensure_ascii=False для корректного отображения кириллицы
    details_json = json.dumps(details, ensure_ascii=False) if details else None

    query = """
    INSERT INTO user_actions_log (user_id, username, action, resource_type, resource_name, details)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        db_manager.execute_query(query, (user_id, display_name, action, resource_type, resource_name, details_json),
                                 commit=True)
        logger.info(
            f"Logged action '{action}' for user '{display_name}' on {resource_type or 'N/A'} '{resource_name or 'N/A'}'")
    except Exception as e:
        logger.error(f"Failed to log action '{action}' for user '{display_name}': {e}")

