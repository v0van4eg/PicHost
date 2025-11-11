import os
import zipfile
import logging
import time
import threading
import shutil
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
        # Оптимизируем количество воркеров
        self.max_workers = max_workers or min(8, (os.cpu_count() or 1) * 2)  # Уменьшил для стабильности
        self.processing_lock = threading.Lock()
        self.active_processes = {}
        # Кэш для путей
        self.path_cache = {}
        self.batch_size = 50  # Размер батча для обработки

    def process_zip(self, zip_path):
        """
        Основной метод обработки ZIP (для совместимости)
        """
        return self.process_zip_fast(zip_path)

    def process_zip_fast(self, zip_path):
        """
        Оптимизированная обработка ZIP с батчингом и кэшированием
        """
        logger.info(f"🚀 Начинаем оптимизированную обработку ZIP: {zip_path}")
        start_time = time.time()

        zip_basename = os.path.basename(zip_path)
        with self.processing_lock:
            if zip_basename in self.active_processes:
                return False, "ZIP уже обрабатывается"
            self.active_processes[zip_basename] = True

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                album_name_raw = os.path.splitext(zip_basename)[0]
                album_name = safe_folder_name(album_name_raw)
                album_path = os.path.join(self.upload_folder, album_name)

                # Быстрая валидация
                if not self._quick_validate_zip(zip_ref):
                    return False, "ZIP не содержит валидных изображений"

                # Очистка превью
                cleanup_album_thumbnails(album_name, self.thumbnail_folder)
                os.makedirs(album_path, exist_ok=True)

                # Получаем список файлов для обработки
                image_files = self._get_image_files(zip_ref)

                if not image_files:
                    return False, "Нет файлов для обработки"

                logger.info(f"📁 Найдено {len(image_files)} изображений, обрабатываем...")

                # Параллельная обработка с батчингом
                files_to_insert = self._process_files_parallel_batch(zip_ref, image_files, album_path, album_name)

                if not files_to_insert:
                    return False, "Не удалось обработать файлы"

                # Удаляем пустые папки
                cleanup_empty_folders(album_path)

                # Батч-вставка в БД
                db_success = self._batch_db_insert(album_name, files_to_insert)

                processing_time = time.time() - start_time
                logger.info(f"✅ ZIP обработан за {processing_time:.2f}s: {len(files_to_insert)} файлов")

                return db_success, album_name

        except Exception as e:
            logger.error(f"❌ Ошибка обработки ZIP {zip_path}: {e}")
            return False, str(e)
        finally:
            with self.processing_lock:
                self.active_processes.pop(zip_basename, None)

    def _get_image_files(self, zip_ref):
        """Быстрое получение списка изображений"""
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}

        return [
            file_info for file_info in zip_ref.infolist()
            if not file_info.is_dir() and
               os.path.splitext(file_info.filename.lower())[1] in allowed_extensions
        ]

    def _process_files_parallel_batch(self, zip_ref, image_files, album_path, album_name):
        """Параллельная обработка файлов батчами"""
        files_to_insert = []
        file_lock = threading.Lock()

        def process_file_batch(file_batch):
            """Обрабатывает батч файлов"""
            batch_results = []
            for file_info in file_batch:
                try:
                    # Извлекаем файл
                    zip_ref.extract(file_info.filename, album_path)
                    original_path = os.path.join(album_path, file_info.filename)

                    if os.path.exists(original_path):
                        file_data = self._process_single_file_fast(original_path, album_name)
                        if file_data:
                            batch_results.append(file_data)
                except Exception as e:
                    logger.error(f"Ошибка обработки {file_info.filename}: {e}")
            return batch_results

        # Разбиваем на батчи
        batches = [image_files[i:i + self.batch_size] for i in range(0, len(image_files), self.batch_size)]

        logger.info(f"🔄 Обрабатываем {len(batches)} батчей по {self.batch_size} файлов")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Запускаем все батчи
            future_to_batch = {
                executor.submit(process_file_batch, batch): i for i, batch in enumerate(batches)
            }

            completed = 0
            for future in as_completed(future_to_batch):
                batch_results = future.result()
                with file_lock:
                    files_to_insert.extend(batch_results)

                completed += 1
                if completed % 5 == 0:  # Логируем каждые 5 батчей
                    logger.info(f"📊 Обработано {completed}/{len(batches)} батчей")

        return files_to_insert

    def _process_single_file_fast(self, file_path, album_name):
        """Быстрая обработка одного файла с кэшированием"""
        try:
            # Используем относительный путь как ключ кэша
            relative_path = os.path.relpath(file_path, self.upload_folder)
            cache_key = f"{album_name}_{relative_path}"

            if cache_key in self.path_cache:
                return self.path_cache[cache_key]

            file_dir = os.path.dirname(relative_path)
            filename = os.path.basename(relative_path)

            # Определяем артикул
            if file_dir and file_dir != '.':
                article_number = safe_folder_name(os.path.basename(file_dir))
                # Нормализуем путь
                normalized_dir = os.path.join(self.upload_folder, album_name, article_number)
                normalized_path = os.path.join(normalized_dir, filename)

                if file_path != normalized_path:
                    os.makedirs(normalized_dir, exist_ok=True)
                    shutil.move(file_path, normalized_path)
                    relative_path = os.path.relpath(normalized_path, self.upload_folder)
            else:
                article_number = safe_folder_name(os.path.splitext(filename)[0])

            # Создаем публичную ссылку
            encoded_path = quote(relative_path.replace(os.sep, '/'), safe='/')
            public_link = f"{self.base_url}/images/{encoded_path}"

            result = (relative_path.replace(os.sep, '/'), album_name, article_number, public_link)

            # Кэшируем результат
            self.path_cache[cache_key] = result
            return result

        except Exception as e:
            logger.error(f"Ошибка обработки файла {file_path}: {e}")
            return None

    def _batch_db_insert(self, album_name, files_to_insert):
        """Оптимизированная батч-вставка в БД"""
        try:
            # Группируем операции для одной транзакции
            operations = [
                ("DELETE FROM files WHERE album_name = %s", (album_name,)),
                ("""INSERT INTO files (filename, album_name, article_number, public_link) 
                    VALUES (%s, %s, %s, %s)""", files_to_insert, True)  # True для executemany
            ]

            logger.info(f"💾 Вставляем {len(files_to_insert)} записей в БД")
            db_manager.execute_in_transaction(operations)
            logger.info("✅ Данные успешно сохранены в БД")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка вставки в БД: {e}")
            return False

    def _quick_validate_zip(self, zip_ref):
        """Быстрая валидация ZIP архива"""
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}

        # Проверяем первые 10 файлов для быстрой валидации
        for file_info in zip_ref.infolist()[:10]:
            if not file_info.is_dir():
                ext = os.path.splitext(file_info.filename.lower())[1]
                if ext in allowed_extensions:
                    return True
        return False

    def get_processing_stats(self):
        """Статистика обработки"""
        return {
            'active_processes': len(self.active_processes),
            'cache_size': len(self.path_cache),
            'max_workers': self.max_workers,
            'batch_size': self.batch_size
        }
