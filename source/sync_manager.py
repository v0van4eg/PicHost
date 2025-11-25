# sync_manager.py
import os
import logging
from urllib.parse import quote
from database import db_manager
from utils import safe_folder_name, cleanup_file_thumbnails

logger = logging.getLogger(__name__)


class SyncManager:
    """
    Менеджер синхронизации базы данных с файловой системой
    """

    def __init__(self, upload_folder, base_url, thumbnail_folder):
        self.upload_folder = upload_folder
        self.base_url = base_url
        self.thumbnail_folder = thumbnail_folder
        self.allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}

    def scan_filesystem(self):
        """
        Сканирует файловую систему и возвращает словарь файлов
        """
        fs_files = {}

        for root, dirs, files in os.walk(self.upload_folder):
            for file in files:
                _, ext = os.path.splitext(file.lower())
                if ext in self.allowed_extensions:
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.upload_folder).replace(os.sep, '/')

                    # Определяем альбом и артикул из пути
                    path_parts = rel_path.split('/')
                    if len(path_parts) >= 1:
                        album_name = path_parts[0]

                        # Если файл находится в подпапке (артикуле)
                        if len(path_parts) >= 3:
                            article_number = path_parts[1]
                        else:
                            # Если файл напрямую в альбоме, используем имя файла без расширения как артикул
                            article_number = os.path.splitext(file)[0]

                        # Обеспечиваем безопасные имена
                        album_name = safe_folder_name(album_name)
                        article_number = safe_folder_name(article_number)

                        encoded_path = quote(rel_path, safe='/')
                        public_link = f"{self.base_url}/images/{encoded_path}"

                        fs_files[rel_path] = {
                            'album_name': album_name,
                            'article_number': article_number,
                            'public_link': public_link
                        }

        return fs_files

    def get_database_files(self):
        """
        Получает все файлы из базы данных
        """
        db_files_result = db_manager.execute_query(
            "SELECT filename, album_name, article_number, public_link FROM files",
            fetch=True
        )

        return {row['filename']: {
            'album_name': row['album_name'],
            'article_number': row['article_number'],
            'public_link': row['public_link']
        } for row in db_files_result} if db_files_result else {}

    def sync(self):
        """
        Основной метод синхронизации базы данных с файловой системой
        Возвращает: (deleted_files, added_files)
        """
        try:
            # Получаем данные из файловой системы и БД
            fs_files = self.scan_filesystem()
            db_files = self.get_database_files()

            # Находим различия
            files_to_delete = set(db_files.keys()) - set(fs_files.keys())
            files_to_add = set(fs_files.keys()) - set(db_files.keys())

            # Подготавливаем операции для транзакции
            operations = self._prepare_operations(files_to_delete, files_to_add, fs_files)

            # Выполняем операции в транзакции
            if operations:
                db_manager.execute_in_transaction(operations)

            # Очищаем превью для удаленных файлов
            self._cleanup_thumbnails(files_to_delete)

            logger.info(f"Sync completed: deleted {len(files_to_delete)} records, added {len(files_to_add)} records")
            return list(files_to_delete), list(files_to_add)

        except Exception as e:
            logger.error(f"Error in sync: {e}")
            raise

    def _prepare_operations(self, files_to_delete, files_to_add, fs_files):
        """
        Подготавливает операции для транзакции
        """
        operations = []

        # Операция удаления
        if files_to_delete:
            delete_query = "DELETE FROM files WHERE filename = ANY(%s)"
            operations.append((delete_query, (list(files_to_delete),)))

        # Операция вставки
        if files_to_add:
            insert_data = []
            for rel_path in files_to_add:
                file_info = fs_files[rel_path]
                insert_data.append((
                    rel_path,
                    file_info['album_name'],
                    file_info['article_number'],
                    file_info['public_link']
                ))

            insert_query = """
                INSERT INTO files (filename, album_name, article_number, public_link) 
                VALUES (%s, %s, %s, %s)
            """
            operations.append((insert_query, insert_data, True))  # True для executemany

        return operations

    def _cleanup_thumbnails(self, files_to_delete):
        """
        Очищает превью для удаленных файлов
        """
        for rel_path in files_to_delete:
            cleanup_file_thumbnails(rel_path, self.upload_folder, self.thumbnail_folder)


    def incremental_sync(self, since_timestamp=None):
        """
        Инкрементальная синхронизация (упрощенная версия)
        В реальном приложении можно использовать файловые метаданные
        """
        return self.sync()

    def get_sync_stats(self):
        """
        Возвращает статистику синхронизации
        """
        try:
            # Статистика по файлам в БД
            db_stats = db_manager.execute_query(
                "SELECT COUNT(*) as total_files FROM files",
                fetch=True
            )

            # Статистика по файлам в файловой системе
            fs_files_count = 0
            for root, dirs, files in os.walk(self.upload_folder):
                for file in files:
                    _, ext = os.path.splitext(file.lower())
                    if ext in self.allowed_extensions:
                        fs_files_count += 1

            return {
                'database_files': db_stats[0]['total_files'] if db_stats else 0,
                'filesystem_files': fs_files_count,
                'sync_status': 'in_sync' if db_stats and db_stats[0]['total_files'] == fs_files_count else 'out_of_sync'
            }

        except Exception as e:
            logger.error(f"Error getting sync stats: {e}")
            return {'error': str(e)}
