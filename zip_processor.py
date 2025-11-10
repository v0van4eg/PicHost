<<<<<<< HEAD
# zip_processor.py - ОПТИМИЗИРОВАННАЯ ВЕРСИЯ

import os
import zipfile
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import db_manager
from urllib.parse import quote
from utils import safe_folder_name, cleanup_album_thumbnails, cleanup_empty_folders

logger = logging.getLogger(__name__)


class ZipProcessor:
    def __init__(self, upload_folder, base_url, thumbnail_folder, max_workers=None):
        self.upload_folder = upload_folder
        self.base_url = base_url
        self.thumbnail_folder = thumbnail_folder
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.processing_lock = threading.Lock()
        self.active_processes = {}

    def process_zip(self, zip_path):
        """
        Оптимизированная обработка ZIP-архива с многопоточностью
        """
        # Проверяем, не обрабатывается ли уже этот архив
        zip_basename = os.path.basename(zip_path)
        with self.processing_lock:
            if zip_basename in self.active_processes:
                return False, "This ZIP file is already being processed"
            self.active_processes[zip_basename] = True

        start_time = time.time()

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                album_name_raw = os.path.splitext(zip_basename)[0]
                album_name = safe_folder_name(album_name_raw)
                album_path = os.path.join(self.upload_folder, album_name)

                # Очистка превью перед обработкой нового альбома
                cleanup_album_thumbnails(album_name, self.thumbnail_folder)
                os.makedirs(album_path, exist_ok=True)

                # Фильтрация только изображений
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                image_files = [
                    file_info for file_info in zip_ref.infolist()
                    if not file_info.is_dir() and
                       os.path.splitext(file_info.filename.lower())[1] in allowed_extensions
                ]

                logger.info(f"Processing {len(image_files)} images with {self.max_workers} workers")

                # Параллельное извлечение файлов
                if len(image_files) > 10:  # Используем многопоточность для больших архивов
                    files_to_insert = self._extract_files_parallel(zip_ref, image_files, album_path, album_name)
                else:
                    files_to_insert = self._extract_files_sequential(zip_ref, image_files, album_path, album_name)

                # Удаляем пустые папки
                cleanup_empty_folders(album_path)

                # Используем одну транзакцию для всех операций
                operations = [
                    ("DELETE FROM files WHERE album_name = %s", (album_name,)),
                    ("""INSERT INTO files (filename, album_name, article_number, public_link) 
                        VALUES (%s, %s, %s, %s)""", files_to_insert, True)
                ]

                logger.info(f"Executing transaction for {len(files_to_insert)} files")
                db_manager.execute_in_transaction(operations)

                processing_time = time.time() - start_time
                logger.info(f"Processed ZIP {zip_path}: {len(files_to_insert)} files in {processing_time:.2f}s")
                return True, album_name

        except Exception as e:
            logger.error(f"Error processing ZIP file {zip_path}: {e}")
            return False, str(e)
        finally:
            with self.processing_lock:
                self.active_processes.pop(zip_basename, None)

    def _extract_files_sequential(self, zip_ref, image_files, album_path, album_name):
        """Последовательное извлечение файлов (для маленьких архивов)"""
        files_to_insert = []

        # Извлекаем все файлы
        zip_ref.extractall(album_path, members=[f.filename for f in image_files])

        # Обрабатываем файлы
        for file_info in image_files:
            original_file_path = os.path.join(album_path, file_info.filename)

            if not os.path.exists(original_file_path):
                continue

            file_data = self._process_single_file(original_file_path, album_name)
            if file_data:
                files_to_insert.append(file_data)

        return files_to_insert

    def _extract_files_parallel(self, zip_ref, image_files, album_path, album_name):
        """Параллельное извлечение и обработка файлов"""
        files_to_insert = []
        file_lock = threading.Lock()

        def process_file(file_info):
            try:
                # Извлекаем отдельный файл
                zip_ref.extract(file_info.filename, album_path)
                original_file_path = os.path.join(album_path, file_info.filename)

                if os.path.exists(original_file_path):
                    return self._process_single_file(original_file_path, album_name)
                return None
            except Exception as e:
                logger.error(f"Error processing file {file_info.filename}: {e}")
                return None

        # Используем ThreadPoolExecutor для параллельной обработки
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(process_file, file_info): file_info
                for file_info in image_files
            }

            for future in as_completed(future_to_file):
                file_data = future.result()
                if file_data:
                    with file_lock:
                        files_to_insert.append(file_data)

        return files_to_insert

    def _process_single_file(self, original_file_path, album_name):
        """Обработка одного файла (вынесено в отдельный метод для многопоточности)"""
        try:
            # Определяем путь относительно upload_folder
            relative_path = os.path.relpath(original_file_path, self.upload_folder)
            file_dir = os.path.dirname(relative_path)
            filename = os.path.basename(relative_path)

            # Определяем артикул
            if file_dir and file_dir != '.':
                # Если файл в подпапке - используем имя папки как артикул
                article_folder_raw = os.path.basename(file_dir)
                article_number = safe_folder_name(article_folder_raw)

                # Нормализуем путь если нужно
                normalized_dir = os.path.join(self.upload_folder, album_name, article_number)
                normalized_path = os.path.join(normalized_dir, filename)

                if original_file_path != normalized_path:
                    os.makedirs(normalized_dir, exist_ok=True)
                    os.rename(original_file_path, normalized_path)
                    original_file_path = normalized_path
                    relative_path = os.path.relpath(original_file_path, self.upload_folder)
            else:
                # Если файл в корне альбома - используем имя файла без расширения как артикул
                article_number = safe_folder_name(os.path.splitext(filename)[0])

            # Создаем публичную ссылку
            encoded_path = quote(relative_path.replace(os.sep, '/'), safe='/')
            public_link = f"{self.base_url}/images/{encoded_path}"

            return (relative_path.replace(os.sep, '/'), album_name, article_number, public_link)

        except Exception as e:
            logger.error(f"Error processing single file {original_file_path}: {e}")
            return None

    def validate_zip_structure(self, zip_path):
        """
        Быстрая валидация ZIP-архива
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                if not file_list:
                    logger.error("ZIP archive is empty")
                    return False

                # Быстрая проверка на наличие изображений
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                for info in zip_ref.infolist()[:10]:  # Проверяем только первые 10 файлов
                    if not info.is_dir():
                        ext = os.path.splitext(info.filename.lower())[1]
                        if ext in allowed_extensions:
                            return True

                logger.error("ZIP archive contains no valid images")
                return False

        except zipfile.BadZipFile:
            logger.error("Invalid ZIP file format")
            return False
        except Exception as e:
            logger.error(f"Error validating ZIP structure: {e}")
            return False

    def get_zip_info(self, zip_path):
        """
        Быстрый анализ содержимого ZIP-архива
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                image_files = [
                    info for info in zip_ref.infolist()
                    if not info.is_dir() and
                       os.path.splitext(info.filename.lower())[1] in allowed_extensions
                ]

                total_size = sum(info.file_size for info in image_files)

                return {
                    'total_files': len(zip_ref.namelist()),
                    'image_files': len(image_files),
                    'total_size': total_size,
                    'album_name': safe_folder_name(os.path.splitext(os.path.basename(zip_path))[0])
                }

        except Exception as e:
            logger.error(f"Error getting ZIP info: {e}")
            return None
=======
# zip_processor.py
import os
import zipfile
import logging
from urllib.parse import quote
from database import db_manager  # Предполагаем, что db_manager доступен
import unicodedata
import re
import time

logger = logging.getLogger(__name__)

class ZipProcessor:
    def __init__(self, upload_folder, base_url, db_manager_instance, update_progress_func,
                 get_file_structure_func, cleanup_album_thumbnails_func, cleanup_file_thumbnails_func,
                 get_all_files_func, sync_db_with_filesystem_func):
        self.upload_folder = upload_folder
        self.base_url = base_url
        self.db_manager = db_manager_instance
        self.update_extraction_progress = update_progress_func # Функция обновления прогресса из app.py
        # Передаём зависимости из app.py
        self.get_file_structure = get_file_structure_func
        self.cleanup_album_thumbnails = cleanup_album_thumbnails_func
        self.cleanup_file_thumbnails = cleanup_file_thumbnails_func
        self.get_all_files = get_all_files_func
        self.sync_db_with_filesystem = sync_db_with_filesystem_func

    def safe_folder_name(self, name: str) -> str:
        """Преобразует строку в безопасное имя папки"""
        if not name:
            return "unnamed"
        name = unicodedata.normalize('NFKD', name)
        name = re.sub(r'[^\w\s-]', '', name, flags=re.UNICODE)
        name = re.sub(r'[-\s]+', '_', name, flags=re.UNICODE).strip('-_')
        return name[:255] if name else "unnamed"

    def cleanup_empty_folders(self, folder_path):
        """Рекурсивно удаляет пустые папки"""
        try:
            for root, dirs, files in os.walk(folder_path, topdown=False):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        if not os.listdir(dir_path): # Папка пуста
                            os.rmdir(dir_path)
                            logger.debug(f"Removed empty folder: {dir_path}")
                    except OSError:
                        pass # Папка не пуста или нет прав
        except Exception as e:
            logger.error(f"Error cleaning up empty folders in {folder_path}: {e}")

    def validate_zip_file(self, file_storage):
        """Проверяет валидность ZIP-файла"""
        try:
            # Проверяем расширение
            if not file_storage.filename.lower().endswith('.zip'):
                return False, "Файл должен быть в формате ZIP"

            # Проверяем сигнатуру ZIP-файла
            file_storage.stream.seek(0)
            signature = file_storage.stream.read(4)
            file_storage.stream.seek(0)
            if signature != b'PK\x03\x04':
                return False, "Некорректный формат ZIP-файла"
            return True, "OK"
        except Exception as e:
            logger.error(f"Error validating ZIP file: {e}")
            return False, f"Ошибка проверки файла: {str(e)}"

    def save_uploaded_zip(self, file_storage):
        """Сохраняет загруженный ZIP-файл во временную папку"""
        try:
            original_name = file_storage.filename
            base_name = os.path.basename(original_name)
            name_without_ext, _ = os.path.splitext(base_name)
            safe_zip_name = self.safe_folder_name(name_without_ext) + '.zip'
            file_path = os.path.join(self.upload_folder, safe_zip_name)
            file_storage.save(file_path)
            return file_path, safe_zip_name
        except Exception as e:
            logger.error(f"Error saving uploaded ZIP: {e}")
            return None, None

    # --- Новый метод для обработки ZIP с прогрессом ---
    def process_zip_with_progress(self, zip_path, session_id):
        """Обрабатывает ZIP-архив с отслеживанием прогресса"""
        try:
            # Импортируем функции, спефичные для app.py, если они не переданы как зависимости
            # или не находятся в том же модуле
            # from app import get_file_structure, cleanup_album_thumbnails, cleanup_file_thumbnails, \
            #              get_all_files, sync_db_with_filesystem, safe_folder_name # Импорт safe_folder_name из app.py

            # Убран импорт, используем переданные зависимости
            # from app import safe_folder_name # Импорт из app.py больше не нужен, используем self.safe_folder_name

            self.update_extraction_progress(session_id, 0, 0, 'Начало обработки архива...')
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_basename = os.path.basename(zip_path)
                album_name_raw = os.path.splitext(zip_basename)[0]
                # album_name = safe_folder_name(album_name_raw) # Используем версию из app.py для согласованности
                album_name = self.safe_folder_name(album_name_raw) # Используем версию из ZipProcessor

                # Очистка превью перед обработкой нового альбома
                self.cleanup_album_thumbnails(album_name) # Вызов из переданной зависимости
                album_path = os.path.join(self.upload_folder, album_name)
                os.makedirs(album_path, exist_ok=True)

                # Получаем список файлов для извлечения
                file_list = [f for f in zip_ref.infolist() if not f.is_dir()]
                total_files = len(file_list)
                # self.update_extraction_progress(session_id, 0, total_files, f'Найдено {total_files} файлов для обработки')
                # time.sleep(0.1) # Убрана задержка из обновления прогресса

                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                files_to_insert = []
                extracted_count = 0

                # Извлечение архива с отслеживанием прогресса
                for i, file_info in enumerate(file_list):
                    try:
                        # Пропускаем не-изображения
                        _, ext = os.path.splitext(file_info.filename.lower())
                        if ext not in allowed_extensions:
                            continue

                        # Извлекаем файл
                        zip_ref.extract(file_info, album_path)
                        extracted_count += 1

                        # Обновляем прогресс каждые 5 файлов или для последнего файла
                        if extracted_count % 5 == 0 or i == len(file_list) - 1:
                            progress_percent = int((extracted_count / total_files) * 100)
                            self.update_extraction_progress(session_id,
                                                            extracted_count,
                                                            total_files,
                                                            f'Распаковано {extracted_count}/{total_files} файлов ({progress_percent}%)')
                            # time.sleep(0.1) # Убрана задержка из обновления прогресса

                    except Exception as e:
                        logger.error(f"Error extracting {file_info.filename}: {e}")
                        continue # Продолжаем с другими файлами

                # Обработка структуры папок и файлов
                # album_structure = get_file_structure(album_path, album_name) # Вызов из app.py
                album_structure = self.get_file_structure(album_path, album_name) # Вызов из переданной зависимости
                files_to_insert = album_structure['files']

                # --- Анализ файловой системы и синхронизация БД ---
                time.sleep(0.5) # Искусственная задержка перед анализом
                # fs_files = get_all_files() # Вызов из app.py
                fs_files = self.get_all_files() # Вызов из переданной зависимости
                # files_to_delete, files_to_add = sync_db_with_filesystem(fs_files, files_to_insert) # Вызов из app.py
                files_to_delete, files_to_add = self.sync_db_with_filesystem(fs_files, files_to_insert) # Вызов из переданной зависимости

                # --- Очистка превью для удаленных файлов ---
                for rel_path in files_to_delete:
                    # cleanup_file_thumbnails(rel_path) # Вызов из app.py
                    self.cleanup_file_thumbnails(rel_path) # Вызов из переданной зависимости

                # --- Финальное обновление прогресса ---
                self.update_extraction_progress(session_id,
                                                total_files,
                                                total_files,
                                                f'Готово! Обработано {len(files_to_insert)} файлов',
                                                is_complete=True)
                # time.sleep(0.1) # Убрана задержка из обновления прогресса
                time.sleep(1) # Искусственная задержка перед завершением

                logger.info(f"Processed ZIP {zip_path}: inserted {len(files_to_insert)} files")
                return True

        except Exception as e:
            logger.error(f"Error processing ZIP file {zip_path}: {e}")
            self.update_extraction_progress(session_id, 0, 0, f'Ошибка: {str(e)}', is_complete=True)
            return False
>>>>>>> 0a7af61 (Вынесение zip_processor в модуль)
