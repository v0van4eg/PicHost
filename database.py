# database.py
import os
import psycopg2
from psycopg2.extras import DictCursor
import logging
import time
from threading import Lock
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        # Собираем DATABASE_URL из отдельных переменных
        user = os.environ.get('POSTGRES_USER', 'postgres')
        password = os.environ.get('POSTGRES_PASSWORD', 'password')
        db_name = os.environ.get('POSTGRES_DB', 'pichosting')
        # Получаем хост и порт из переменных окружения
        host = os.environ.get('POSTGRES_HOST', 'db')  # Используем 'db' как значение по умолчанию
        port = os.environ.get('POSTGRES_PORT', '5432')  # Стандартный порт

        self.database_url = f'postgresql://{user}:{password}@{host}:{port}/{db_name}'

        logger.info(f"Database URL constructed for host: {host}, port: {port}, db: {db_name}")  # Для отладки

        self.conn = None
        self.lock = Lock()
        self.last_connection_time = 0
        self.connection_timeout = 300  # 5 минут

    def get_connection(self):
        with self.lock:
            current_pid = os.getpid()
            current_time = time.time()

            # Если PID изменился (форк) ИЛИ соединение мертво ИЛИ таймаут — пересоздать
            if (
                self.conn is None or
                self.conn.closed != 0 or
                current_pid != self.pid or
                current_time - self.last_connection_time > self.connection_timeout
            ):
                self._close_connection()
                self._create_connection()
                self.pid = current_pid  # Обновляем PID

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
                    if cursor.description:  # Проверяем, есть ли результаты для выборки
                        result = cursor.fetchall()
                        return [dict(row) for row in result]
                    else:
                        return []  # Возвращаем пустой список, если fetch, но нет результата
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
                    time.sleep(retry_delay * (attempt + 1))  # Увеличиваем задержку с каждой попыткой
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

    @contextmanager
    def transaction(self):
        """
        Контекстный менеджер для выполнения операций в транзакции.
        Пример использования:
        with db_manager.transaction() as cursor:
            cursor.execute("DELETE FROM files WHERE album_name = %s", (album_name,))
            cursor.executemany(insert_query, files_to_insert)
        """
        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            yield cursor
            conn.commit()
            logger.debug("Transaction committed successfully")
        except Exception as e:
            if conn:
                conn.rollback()
                logger.error("Transaction rolled back due to error")
            raise
        finally:
            if cursor:
                cursor.close()

    def execute_in_transaction(self, operations):
        """
        Выполняет несколько операций в одной транзакции.
        :param operations: список кортежей (query, params) или (query, params, executemany_flag)
        :return: True если успешно, иначе исключение
        """
        conn = None
        cursor = None
        logger.info(f"Запускаем транзакцию с {len(operations)} операциями")
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            for operation in operations:
                if len(operation) == 3 and operation[2]:
                    # executemany операция
                    query, params_list, _ = operation
                    cursor.executemany(query, params_list)
                else:
                    # execute операция
                    query, params = operation[:2]
                    cursor.execute(query, params)

            conn.commit()
            logger.info(f"Транзакция успешна: {len(operations)} operations")
            return True

        except Exception as e:
            if conn:
                conn.rollback()
                logger.error(f"Transaction failed after {len(operations)} operations: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def batch_execute(self, query, params_list, batch_size=1000):
        """
        Выполняет пакетные операции с разбивкой на части.
        :param query: SQL запрос
        :param params_list: список параметров для executemany
        :param batch_size: размер батча
        :return: общее количество обработанных строк
        """
        total_affected = 0
        for i in range(0, len(params_list), batch_size):
            batch = params_list[i:i + batch_size]
            with self.transaction() as cursor:
                cursor.executemany(query, batch)
                total_affected += cursor.rowcount or 0
            logger.debug(f"Processed batch {i // batch_size + 1}/{(len(params_list) - 1) // batch_size + 1}")

        logger.info(f"Batch execute completed: {total_affected} rows affected")
        return total_affected

    def execute_many(self, query, params_list):
        """
        Выполняет операцию executemany в транзакции.
        :param query: SQL запрос
        :param params_list: список параметров
        :return: количество обработанных строк
        """
        with self.transaction() as cursor:
            cursor.executemany(query, params_list)
            return cursor.rowcount or 0

    def close(self):
        """Закрытие всех соединений"""
        self._close_connection()

    # Поддержка контекстного менеджера для использования в with блоках
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер - соединение управляется классом"""
        pass


# Глобальный экземпляр менеджера БД
db_manager = DatabaseManager()
