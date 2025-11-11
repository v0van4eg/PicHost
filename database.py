import os
import psycopg2
from psycopg2.extras import DictCursor, execute_batch
import logging
import time
from threading import Lock
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        # Конфигурация из переменных окружения
        user = os.environ.get('POSTGRES_USER', 'postgres')
        password = os.environ.get('POSTGRES_PASSWORD', 'password')
        db_name = os.environ.get('POSTGRES_DB', 'pichosting')
        host = os.environ.get('POSTGRES_HOST', 'db')
        port = os.environ.get('POSTGRES_PORT', '5432')

        self.database_url = f'postgresql://{user}:{password}@{host}:{port}/{db_name}'

        self.conn = None
        self.lock = Lock()
        self.connection_pool = []
        self.max_pool_size = 5
        self.pool_lock = Lock()
        self.pid = os.getpid()
        self.last_connection_time = 0
        self.connection_timeout = 300

        logger.info(f"🔧 Инициализирован менеджер БД для {host}:{port}")

    def get_connection(self):
        """Получение соединения с пулом"""
        with self.pool_lock:
            current_pid = os.getpid()
            current_time = time.time()

            # Если PID изменился (форк) ИЛИ соединение мертво ИЛИ таймаут — пересоздать
            if (
                    self.conn is None or
                    (hasattr(self.conn, 'closed') and self.conn.closed != 0) or
                    current_pid != self.pid or
                    current_time - self.last_connection_time > self.connection_timeout
            ):
                self._close_connection()
                self._create_connection()
                self.pid = current_pid

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
        if self.conn and hasattr(self.conn, 'closed') and self.conn.closed == 0:
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

    @contextmanager
    def transaction(self):
        """
        Контекстный менеджер для выполнения операций в транзакции.
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

    # Новые оптимизированные методы

    @contextmanager
    def get_cursor(self):
        """Контекстный менеджер для работы с курсором"""
        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()

    def execute_batch_optimized(self, query, params_list, batch_size=1000):
        """
        Оптимизированная батч-вставка с использованием execute_batch
        """
        total_rows = 0
        start_time = time.time()

        for i in range(0, len(params_list), batch_size):
            batch = params_list[i:i + batch_size]

            with self.get_cursor() as cursor:
                execute_batch(cursor, query, batch)
                total_rows += len(batch)

            if (i // batch_size) % 10 == 0:  # Логируем каждые 10 батчей
                logger.info(f"📊 Обработано {i + len(batch)}/{len(params_list)} записей")

        elapsed = time.time() - start_time
        logger.info(f"✅ Батч-вставка завершена: {total_rows} строк за {elapsed:.2f}s")
        return total_rows

    def bulk_insert_files(self, files_data):
        """
        Массовая вставка файлов с оптимизацией
        """
        query = """
            INSERT INTO files (filename, album_name, article_number, public_link) 
            VALUES (%s, %s, %s, %s)
        """

        return self.execute_batch_optimized(query, files_data, batch_size=500)

    def bulk_delete_files(self, filenames, batch_size=1000):
        """
        Массовое удаление файлов
        """
        total_deleted = 0

        for i in range(0, len(filenames), batch_size):
            batch = filenames[i:i + batch_size]

            with self.get_cursor() as cursor:
                cursor.execute(
                    "DELETE FROM files WHERE filename = ANY(%s)",
                    (batch,)
                )
                total_deleted += cursor.rowcount or 0

        logger.info(f"🗑️ Удалено {total_deleted} записей")
        return total_deleted

    def get_files_by_album_fast(self, album_name):
        """
        Быстрое получение файлов по альбому
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT filename, album_name, article_number, public_link, created_at 
                FROM files 
                WHERE album_name = %s 
                ORDER BY article_number, filename
            """, (album_name,))

            return [dict(row) for row in cursor.fetchall()]

    def get_albums_fast(self):
        """Быстрое получение списка альбомов"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT album_name, 
                       COUNT(*) as file_count,
                       MAX(created_at) as last_updated
                FROM files 
                GROUP BY album_name 
                ORDER BY album_name
            """)

            return [dict(row) for row in cursor.fetchall()]

    def cleanup_old_connections(self):
        """Очистка старых соединений"""
        # В этой реализации используем базовую логику
        pass

    def close_all(self):
        """Закрытие всех соединений"""
        self._close_connection()

    def close(self):
        """Закрытие соединения (для совместимости)"""
        self._close_connection()

    # Поддержка контекстного менеджера для использования в with блоках
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер - соединение управляется классом"""
        pass


# Глобальный экземпляр
db_manager = DatabaseManager()
