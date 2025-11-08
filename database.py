# database.py
import os
import psycopg2
from psycopg2.extras import DictCursor
import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        # Собираем DATABASE_URL из отдельных переменных
        user = os.environ.get('POSTGRES_USER', 'postgres')
        password = os.environ.get('POSTGRES_PASSWORD', 'password')
        db_name = os.environ.get('POSTGRES_DB', 'pichosting')
        # Получаем хост и порт из переменных окружения
        host = os.environ.get('POSTGRES_HOST', 'db') # Используем 'db' как значение по умолчанию
        port = os.environ.get('POSTGRES_PORT', '5432') # Стандартный порт

        self.database_url = f'postgresql://{user}:{password}@{host}:{port}/{db_name}'

        logger.info(f"Database URL constructed for host: {host}, port: {port}, db: {db_name}") # Для отладки

        self.conn = None
        self.lock = Lock()
        self.last_connection_time = 0
        self.connection_timeout = 300 # 5 минут

    def get_connection(self):
        """Получение соединения с проверкой состояния"""
        with self.lock:
            current_time = time.time()
            # Проверяем нужно ли переподключиться
            if (self.conn is None or
                self.conn.closed != 0 or
                current_time - self.last_connection_time > self.connection_timeout):
                self._close_connection()
                self._create_connection()
            return self.conn

    def _create_connection(self):
        """Создание нового соединения"""
        try:
            self.conn = psycopg2.connect(
                self.database_url,
                cursor_factory=DictCursor,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
            self.conn.autocommit = False
            self.last_connection_time = time.time()
            logger.info("New database connection created")
        except Exception as e:
            logger.error(f"Failed to create database connection: {e}")
            raise

    def _close_connection(self):
        """Закрытие соединения"""
        if self.conn and self.conn.closed == 0:
            try:
                self.conn.close()
                logger.info("Database connection closed")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")
        self.conn = None

    def execute_query(self, query, params=None, fetch=False, commit=False):
        """Универсальная функция выполнения запросов с повторными попытками"""
        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            conn = None
            cursor = None
            try:
                conn = self.get_connection()
                cursor = conn.cursor()
                cursor.execute(query, params)

                if commit:
                    conn.commit()

                if fetch:
                    if cursor.description: # Проверяем, есть ли результаты для выборки
                        result = cursor.fetchall()
                        return [dict(row) for row in result]
                    else:
                        return [] # Возвращаем пустой список, если fetch, но нет результата
                else:
                    return cursor.rowcount

            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                logger.warning(f"Database connection error (attempt {attempt + 1}/{max_retries}): {e}")
                # Принудительно закрываем соединение при ошибке
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                    self._close_connection()

                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1)) # Увеличиваем задержку с каждой попыткой
                    continue
                else:
                    logger.error(f"Failed to execute query after {max_retries} attempts: {e}")
                    raise
            except Exception as e:
                logger.error(f"Database error: {e}")
                if conn:
                    try:
                        conn.rollback()
                    except:
                        pass
                raise
            finally:
                if cursor:
                    cursor.close()
                # Не закрываем соединение здесь - оно управляется классом

    def close(self):
        """Закрытие всех соединений"""
        self._close_connection()

# Глобальный экземпляр менеджера БД
db_manager = DatabaseManager()
