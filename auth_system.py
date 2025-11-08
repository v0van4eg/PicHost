# auth_system.py - исправленная версия с фильтрацией ролей и отдельным шаблоном профиля

from flask import session, redirect, url_for, request, flash, render_template # Добавлен render_template
from functools import wraps
import base64
import json
import secrets
import os
from authlib.integrations.flask_client import OAuth


class AuthManager:
    def __init__(self, app=None):
        self.oauth = None
        self.app = None
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

        # Конфигурация фильтрации ролей
        self.custom_roles_prefix = os.getenv('CUSTOM_ROLES_PREFIX', 'app')  # Роли начинающиеся с этого префикса
        self.hide_default_roles = os.getenv('HIDE_DEFAULT_ROLES', 'true').lower() == 'true'

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

    def _filter_custom_roles(self, roles):
        """Фильтрует роли, оставляя только кастомные"""
        if not self.hide_default_roles:
            return roles

        filtered_roles = []
        for role in roles:
            # Оставляем только роли с заданным префиксом
            if role.startswith(self.custom_roles_prefix):
                filtered_roles.append(role)

        self.app.logger.info(f"Role filtering: {len(roles)} -> {len(filtered_roles)} roles")
        self.app.logger.info(f"Filtered roles: {filtered_roles}")
        return filtered_roles

    def register_routes(self):
        """Регистрация маршрутов аутентификации"""

        @self.app.route('/login')
        def login():
            return self._handle_login()

        @self.app.route('/auth/callback')
        def auth_callback():
            return self._handle_callback()

        @self.app.route('/logout')
        def logout():
            return self._handle_logout()

        @self.app.route('/profile')
        @login_required
        def profile():
            """Страница профиля пользователя"""
            user = session.get('user', {})
            # Извлекаем имя и фамилию из данных пользователя
            given_name = user.get('given_name', '').strip()
            family_name = user.get('family_name', '').strip()
            full_name = f"{given_name} {family_name}".strip() or user.get('name', 'Не указано')

            # Получаем отфильтрованные роли для отображения
            display_roles = user.get('display_roles', [])
            all_roles = user.get('roles', [])

            # Проверяем, есть ли у пользователя роль appadmin
            is_appadmin = 'appadmin' in all_roles # или display_roles, в зависимости от вашей логики

            # Подготовим словарь с информацией о пользователе для шаблона
            user_info = {
                'name': user.get('name', 'Не указано'),
                'given_name': given_name,
                'family_name': family_name,
                'full_name': full_name,
                'email': user.get('email', 'Не указан'),
                'sub': user.get('sub', 'Не указан')
            }

            return render_template('profile.html',
                                   user_info=user_info,
                                   display_roles=display_roles,
                                   all_roles=all_roles,
                                   is_appadmin=is_appadmin)

    def _handle_login(self):
        """Обработка входа"""
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

            # Извлекаем роли
            realm_access = decoded_token.get('realm_access', {})
            resource_access = decoded_token.get('resource_access', {})

            realm_roles = realm_access.get('roles', [])
            client_roles = []

            # Получаем роли клиента
            client_id = self.keycloak.client_id
            if client_id in resource_access:
                client_roles = resource_access[client_id].get('roles', [])

            all_roles = realm_roles + client_roles

            # ФИЛЬТРАЦИЯ РОЛЕЙ: оставляем только кастомные
            display_roles = self._filter_custom_roles(all_roles)

            # Сохраняем пользователя в сессии
            session['user'] = {
                'name': user_info.get('preferred_username', user_info.get('email', 'Unknown')),
                'given_name': user_info.get('given_name', ''),
                'family_name': user_info.get('family_name', ''),
                'email': user_info.get('email', 'No email'),
                'sub': user_info.get('sub'),
                'roles': all_roles,  # Все роли (для проверок)
                'display_roles': display_roles,  # Только отображаемые роли
                'realm_roles': realm_roles,
                'client_roles': client_roles
            }
            session['access_token'] = token['access_token']
            session['id_token'] = token.get('id_token')
            session.permanent = True

            self.app.logger.info(f"User {user_info.get('preferred_username')} logged in successfully")
            self.app.logger.info(f"User roles - All: {all_roles}, Display: {display_roles}")
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


# Декораторы для защиты маршрутов
def login_required(f):
    """Декоратор для проверки аутентификации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def role_required(required_roles):
    """Декоратор для проверки ролей пользователя"""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user'):
                return redirect(url_for('login', next=request.url))

            user_roles = session['user'].get('roles', [])  # Проверяем по всем ролям

            # Проверяем есть ли хотя бы одна из требуемых ролей
            if not any(role in user_roles for role in required_roles):
                user_roles_str = ', '.join(user_roles) if user_roles else 'Нет ролей'
                required_roles_str = ', '.join(required_roles)
                return f'''
                <h1>Доступ запрещен</h1>
                <p>У вас недостаточно прав для доступа к этой странице.</p>
                <p><strong>Ваши роли:</strong> {user_roles_str}</p>
                <p><strong>Требуемые роли:</strong> {required_roles_str}</p>
                <a href="/">На главную</a>
                ''', 403

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f):
    """Декоратор для проверки прав администратора"""
    return role_required(['appadmin', 'administrator'])(f)


# Утилиты для работы с пользователями
def get_current_user():
    """Возвращает текущего пользователя"""
    return session.get('user')


def user_has_role(role):
    """Проверяет, есть ли у пользователя указанная роль"""
    user = get_current_user()
    return user and role in user.get('roles', [])  # Проверяем по всем ролям


def get_user_roles():
    """Возвращает роли текущего пользователя"""
    user = get_current_user()
    return user.get('roles', []) if user else []


def get_display_roles():
    """Возвращает только отображаемые роли текущего пользователя"""
    user = get_current_user()
    return user.get('display_roles', []) if user else []


def is_authenticated():
    """Проверяет, аутентифицирован ли пользователь"""
    return 'user' in session


# Контекстные процессоры для шаблонов
def auth_context_processor():
    """Добавляет переменные аутентификации в контекст шаблонов"""
    return {
        'current_user': get_current_user(),
        'is_authenticated': is_authenticated(),
        'user_has_role': user_has_role,
        'user_roles': get_user_roles(),
        'display_roles': get_display_roles,  # Добавляем функцию для получения отображаемых ролей
        'is_app_admin': is_app_admin,
        'is_app_user': is_app_user
    }


def user_has_any_role(roles):
    """Проверяет, есть ли у пользователя хотя бы одна из указанных ролей"""
    user = get_current_user()
    if not user:
        return False
    user_roles = user.get('roles', [])
    return any(role in user_roles for role in roles)


def is_app_admin():
    """Проверяет, является ли пользователь appadmin"""
    return user_has_any_role(['appadmin'])


def is_app_user():
    """Проверяет, является ли пользователь appuser"""
    return user_has_any_role(['appuser', 'appadmin'])
