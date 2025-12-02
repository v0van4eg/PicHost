# auth_system.py

import base64
import json
import logging
import os
import secrets
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import session, redirect, url_for, request, render_template, current_app

from utils import log_user_login, log_user_logout

logger = logging.getLogger(__name__)


# Система пермишенов
class Permissions:
    # Просмотр
    VIEW_ALBUMS = 'view_albums'
    VIEW_ARTICLES = 'view_articles'
    VIEW_FILES = 'view_files'

    # Загрузка
    UPLOAD_ZIP = 'upload_zip'

    # Управление
    MANAGE_ALBUMS = 'manage_albums'
    MANAGE_ARTICLES = 'manage_articles'
    EXPORT_DATA = 'export_data'

    # Администрирование
    ACCESS_ADMIN = 'access_admin'
    VIEW_LOGS = 'view_logs'
    SYNC_DATABASE = 'sync_database'


# Маппинг ролей на пермишены
ROLE_PERMISSIONS = {
    'appviewer': [
        Permissions.VIEW_ALBUMS,
        Permissions.VIEW_ARTICLES,
        Permissions.VIEW_FILES,
        Permissions.EXPORT_DATA
    ],
    'appuser': [
        Permissions.VIEW_ALBUMS,
        Permissions.VIEW_ARTICLES,
        Permissions.VIEW_FILES,
        Permissions.UPLOAD_ZIP,
        Permissions.EXPORT_DATA
    ],
    'appadmin': [
        Permissions.VIEW_ALBUMS,
        Permissions.VIEW_ARTICLES,
        Permissions.VIEW_FILES,
        Permissions.UPLOAD_ZIP,
        Permissions.MANAGE_ALBUMS,
        Permissions.MANAGE_ARTICLES,
        Permissions.EXPORT_DATA,
        Permissions.ACCESS_ADMIN,
        Permissions.VIEW_LOGS,
        Permissions.SYNC_DATABASE
    ]
}


class AuthManager:
    def __init__(self, app=None):
        self.oauth = None
        self.app = None
        self.role_permissions = ROLE_PERMISSIONS
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Инициализация аутентификации с приложением Flask"""
        self.app = app
        self.oauth = OAuth(app)

        # Получение конфигурации из переменных окружения
        client_id = os.getenv('OAUTH_CLIENT_ID')
        client_secret = os.getenv('OAUTH_CLIENT_SECRET')
        metadata_url = os.getenv('OAUTH_METADATA_URL')
        scope = os.getenv('OAUTH_SCOPE', 'openid profile email')
        code_challenge_method = os.getenv('OAUTH_CODE_CHALLENGE_METHOD', 'S256')

        # Упрощенная конфигурация ролей
        self.allowed_roles = ['appadmin', 'appuser', 'appviewer']

        # Проверка обязательных параметров
        if not client_id:
            raise ValueError("OAUTH_CLIENT_ID environment variable is required")
        if not client_secret:
            raise ValueError("OAUTH_CLIENT_CLIENT_SECRET environment variable is required")
        if not metadata_url:
            raise ValueError("OAUTH_METADATA_URL environment variable is required")

        try:
            self.keycloak = self.oauth.register(
                name='keycloak',
                client_id=client_id,
                client_secret=client_secret,
                server_metadata_url=metadata_url,
                client_kwargs={
                    'scope': scope,
                    'code_challenge_method': code_challenge_method
                },
                # Явно указываем endpoints если metadata недоступна
                api_base_url=os.getenv('OAUTH_BASE_URL', ''),
                access_token_url=os.getenv('OAUTH_ACCESS_TOKEN_URL', ''),
                authorize_url=os.getenv('OAUTH_AUTHORIZE_URL', ''),
            )
        except Exception as e:
            app.logger.error(f"Failed to register OAuth client: {e}")
            raise

    def _filter_user_roles(self, all_roles):
        """Фильтрует роли, оставляя только разрешенные"""
        user_roles = []
        for role in all_roles:
            if role in self.allowed_roles:
                user_roles.append(role)

        self.app.logger.info(f"Role filtering: {len(all_roles)} -> {len(user_roles)} roles")
        self.app.logger.info(f"User roles: {user_roles}")
        return user_roles

    def _get_user_permissions(self, user_roles):
        """Получить все пермишены пользователя на основе ролей"""
        permissions = set()
        for role in user_roles:
            if role in self.role_permissions:
                permissions.update(self.role_permissions[role])
        return permissions

    def user_has_permission(self, user, permission):
        """Проверить наличие пермишена у пользователя"""
        user_roles = user.get('user_roles', [])
        user_permissions = self._get_user_permissions(user_roles)
        return permission in user_permissions

    def register_routes(self):
        """Регистрация маршрутов аутентификации"""

        @self.app.route('/login')
        def login():
            logger.info("Запуск процесса аутентификации")
            return self._handle_login()

        @self.app.route('/auth/callback')
        def auth_callback():
            return self._handle_callback()

        @self.app.route('/logout')
        def logout():
            return self._handle_logout()

    def _handle_login(self):
        """Обработка входа"""
        logger.info("обработчик входа")
        try:
            nonce = secrets.token_urlsafe(16)
            session['nonce'] = nonce
            session['login_redirect'] = request.args.get('next', url_for('index'))

            redirect_uri = url_for('auth_callback', _external=True)
            self.app.logger.info(f"Starting OAuth flow with redirect_uri: {redirect_uri}")

            return self.keycloak.authorize_redirect(redirect_uri, nonce=nonce)
        except Exception as e:
            self.app.logger.error(f"Login error: {str(e)}")
            return f'''
            <h1>Ошибка входа</h1>
            <p>Не удалось инициализировать процесс аутентификации: {str(e)}</p>
            <a href="/">На главную</a>
            ''', 500

    def _handle_callback(self):
        """Обработка OAuth callback"""
        try:
            # Получаем токен
            token = self.keycloak.authorize_access_token()
            nonce = session.pop('nonce', None)
            redirect_to = session.pop('login_redirect', url_for('index'))

            if nonce is None:
                return 'Сессия устарела. Попробуйте войти снова.', 400

            # Верифицируем ID токен
            user_info = self.keycloak.parse_id_token(token, nonce=nonce)

            # Декодируем access token для получения ролей
            access_token = token['access_token']
            decoded_token = self._decode_jwt_payload(access_token)

            # Извлекаем роли из ресурса (client roles)
            resource_access = decoded_token.get('resource_access', {})
            client_roles = []

            # Получаем роли клиента
            client_id = self.keycloak.client_id
            if client_id in resource_access:
                client_roles = resource_access[client_id].get('roles', [])

            # ФИЛЬТРАЦИЯ РОЛЕЙ: оставляем только разрешенные роли
            user_roles = self._filter_user_roles(client_roles)

            # НОВАЯ ЛОГИКА: если у пользователя нет ролей, назначаем appviewer по умолчанию
            has_default_role = False
            if not user_roles:
                # Назначаем роль по умолчанию
                user_roles = ['appviewer']
                has_default_role = True
                self.app.logger.info(
                    f"User {user_info.get('preferred_username')} has no roles, assigned default role: appviewer")

            # Получаем пермишены пользователя
            user_permissions = self._get_user_permissions(user_roles)

            # МИНИМАЛЬНЫЕ ДАННЫЕ В СЕССИИ
            session_user_data = {
                'sub': user_info.get('sub'),
                'name': user_info.get('preferred_username', user_info.get('email', 'Unknown')),
                'email': user_info.get('email', ''),
                'given_name': user_info.get('given_name', ''),
                'family_name': user_info.get('family_name', ''),
                'user_roles': user_roles,  # Только отфильтрованные роли
                'user_permissions': list(user_permissions),  # Список пермишенов
                'has_default_role': has_default_role  # Флаг, что роль назначена по умолчанию
            }

            session['user'] = session_user_data
            session['id_token'] = token.get('id_token')  # Только для logout
            session['last_activity'] = datetime.now().isoformat()  # Устанавливаем время последней активности при логине
            session.permanent = True

            # ЛОГИРОВАНИЕ УСПЕШНОГО ВХОДА
            try:
                log_user_login(session_user_data, 'oauth')
            except Exception as log_error:
                self.app.logger.error(f"Failed to log user login: {log_error}")

            self.app.logger.info(f"User {user_info.get('preferred_username')} logged in successfully")
            self.app.logger.info(f"User roles: {user_roles} (default: {has_default_role})")
            self.app.logger.info(f"User permissions: {user_permissions}")
            return redirect(redirect_to)

        except Exception as e:
            self.app.logger.error(f"Auth callback error: {str(e)}")
            return f'''
            <h1>Ошибка авторизации</h1>
            <p>{str(e)}</p>
            <a href="/">На главную</a> | 
            <a href="/login">Попробовать снова</a>
            ''', 400

    def _handle_logout(self):
        """Обработка выхода с переходом на /hello"""
        try:
            # ЛОГИРОВАНИЕ ВЫХОДА (перед очисткой сессии)
            user_info = session.get('user')
            if user_info:
                try:
                    log_user_logout(user_info)
                except Exception as log_error:
                    self.app.logger.error(f"Failed to log user logout: {log_error}")

            # Получаем URL для редиректа после выхода - теперь всегда на /hello
            post_logout_redirect_uri = url_for('hello', _external=True)
            id_token = session.get('id_token')

            # Формируем URL выхода из Keycloak
            logout_url = self._create_logout_url(post_logout_redirect_uri, id_token)

            # Очищаем сессию
            session.clear()

            self.app.logger.info("User logged out successfully, redirecting to /hello")
            return redirect(logout_url)
        except Exception as e:
            self.app.logger.error(f"Logout error: {str(e)}")
            session.clear()
            # При ошибке тоже редиректим на /hello
            return redirect(url_for('hello'))

    def _decode_jwt_payload(self, token):
        """Декодирует JWT payload без проверки подписи"""
        try:
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError("Invalid token format")

            payload = parts[1]
            # Добавляем padding если необходимо
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding

            decoded_bytes = base64.urlsafe_b64decode(payload)
            decoded_str = decoded_bytes.decode('utf-8')
            return json.loads(decoded_str)
        except Exception as e:
            self.app.logger.error(f"Token decode error: {str(e)}")
            return {}

    def _create_logout_url(self, post_logout_redirect_uri, id_token=None):
        """Создает URL для выхода из Keycloak"""
        try:
            # Извлекаем базовый URL из metadata
            metadata = self.keycloak.load_server_metadata()
            logout_endpoint = metadata.get('end_session_endpoint',
                                           os.getenv('OAUTH_LOGOUT_URL', ''))

            if not logout_endpoint:
                raise ValueError("Logout endpoint not found")

            logout_url = f"{logout_endpoint}?post_logout_redirect_uri={post_logout_redirect_uri}"

            if id_token:
                logout_url += f'&id_token_hint={id_token}'
            else:
                # Если нет id_token, используем client_id
                logout_url += f'&client_id={self.keycloak.client_id}'

            return logout_url
        except Exception as e:
            self.app.logger.error(f"Error creating logout URL: {e}")
            # Fallback: просто очищаем сессию и редиректим на /hello
            return url_for('hello')


# auth_system.py

def permission_required(permission):
    """Единственный декоратор для проверки логина и прав"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Проверка аутентификации
            if not session.get('user'):
                return redirect(url_for('login', next=request.url))

            # Проверка пермишена
            user = session['user']
            auth_manager = current_app.config.get('auth_manager')

            if not auth_manager or not auth_manager.user_has_permission(user, permission):
                return f'''
                <h1>Доступ запрещен</h1>
                <p>У вас недостаточно прав для выполнения этого действия.</p>
                <a href="/">На главную</a>
                ''', 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


# Утилиты для работы с пользователями
def get_current_user():
    """Возвращает текущего пользователя"""
    return session.get('user')


def user_has_role(role):
    """Проверяет, есть ли у пользователя указанная роль"""
    user = get_current_user()
    return user and role in user.get('user_roles', [])  # Проверяем по отфильтрованным ролям


def get_user_roles():
    """Возвращает роли текущего пользователя"""
    user = get_current_user()
    return user.get('user_roles', []) if user else []


def is_authenticated():
    """Проверяет, аутентифицирован ли пользователь"""
    return 'user' in session


def user_has_permission(permission):
    """Проверяет, есть ли у пользователя указанный пермишен"""
    user = get_current_user()
    if not user:
        return False

    user_permissions = user.get('user_permissions', [])
    return permission in user_permissions


# Контекстные процессоры для шаблонов
def auth_context_processor():
    """Добавляет переменные аутентификации в контекст шаблонов"""
    user = get_current_user()
    is_auth = is_authenticated()

    # Получаем все пермишены пользователя
    user_permissions = user.get('user_permissions', []) if user else []

    return {
        'current_user': user,
        'is_authenticated': is_auth,
        'user_has_role': user_has_role,
        'user_roles': get_user_roles(),
        'user_permissions': user_permissions,
        'has_permission': lambda perm: perm in user_permissions,
        'Permissions': Permissions,
    }
