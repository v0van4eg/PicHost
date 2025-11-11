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
        self.max_workers = max_workers or min(8, (os.cpu_count() or 1) * 2)
        self.processing_lock = threading.Lock()
        self.active_processes = {}
        # Кэш для путей
        self.path_cache = {}
        self.batch_size = 100  # Увеличили размер батча

    def process_zip(self, zip_path):
        """
        Основной метод обработки ZIP
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

                # Батч-вставка в БД - используем быстрый метод
                db_success = self._batch_db_insert_fast(album_name, files_to_insert)

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
        """Параллельная обработка файлов с оптимизацией блокировок"""
        files_to_insert = []

        # Автоматически подбираем размер батча
        batch_size = min(200, max(50, len(image_files) // (self.max_workers * 2)))
        batches = [image_files[i:i + batch_size] for i in range(0, len(image_files), batch_size)]

        logger.info(f"🔄 Обрабатываем {len(batches)} батчей по {batch_size} файлов")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Собираем результаты без блокировки на каждой итерации
            future_results = []

            for batch in batches:
                future = executor.submit(self._process_file_batch, zip_ref, batch, album_path, album_name)
                future_results.append(future)

            # Ждем завершения всех батчей
            for future in as_completed(future_results):
                try:
                    batch_results = future.result(timeout=300)  # Таймаут 5 минут
                    files_to_insert.extend(batch_results)
                except Exception as e:
                    logger.error(f"Ошибка обработки батча: {e}")

        return files_to_insert

    def _process_file_batch(self, zip_ref, file_batch, album_path, album_name):
        """Обрабатывает батч файлов (вынесено для уменьшения блокировок)"""
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

    def _batch_db_insert_fast(self, album_name, files_to_insert):
        """Ультра-быстрая вставка с использованием UNNEST"""
        try:
            if not files_to_insert:
                return True

            logger.info(f"💾 Быстрая вставка {len(files_to_insert)} записей")
            start_time = time.time()

            # Подготавливаем данные для UNNEST
            filenames = [f[0] for f in files_to_insert]
            album_names = [f[1] for f in files_to_insert]
            article_numbers = [f[2] for f in files_to_insert]
            public_links = [f[3] for f in files_to_insert]

            operations = [
                # Удаляем старые записи
                ("DELETE FROM files WHERE album_name = %s", (album_name,)),

                # Массовая вставка с UNNEST
                ("""
                INSERT INTO files (filename, album_name, article_number, public_link)
                SELECT 
                    unnest(%s::text[]) as filename,
                    unnest(%s::text[]) as album_name, 
                    unnest(%s::text[]) as article_number,
                    unnest(%s::text[]) as public_link
                """, (filenames, album_names, article_numbers, public_links))
            ]

            success = db_manager.execute_in_transaction(operations)

            elapsed = time.time() - start_time
            if success:
                logger.info(f"✅ Данные вставлены за {elapsed:.2f}s ({len(files_to_insert) / elapsed:.1f} записей/сек)")
                return True
            else:
                logger.error(f"❌ Ошибка вставки за {elapsed:.2f}s")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка быстрой вставки: {e}")
            return False

    def _batch_db_insert_copy(self, album_name, files_to_insert):
        """Оптимизированная батч-вставка в БД с использованием COPY"""
        try:
            if not files_to_insert:
                return True

            logger.info(f"💾 Начинаем вставку {len(files_to_insert)} записей в БД (COPY)")
            start_time = time.time()

            # Используем более эффективный подход с временной таблицей
            operations = [
                # Создаем временную таблицу для быстрой загрузки
                ("""
                CREATE TEMP TABLE temp_files (
                    filename TEXT,
                    album_name TEXT,
                    article_number TEXT,
                    public_link TEXT
                ) ON COMMIT DROP
                """, ()),

                # Используем COPY для быстрой загрузки данных
                ("""
                COPY temp_files (filename, album_name, article_number, public_link) 
                FROM STDIN
                """, files_to_insert, 'copy'),  # Специальный флаг для COPY

                # Удаляем старые записи альбома
                ("DELETE FROM files WHERE album_name = %s", (album_name,)),

                # Вставляем данные из временной таблицы
                ("""
                INSERT INTO files (filename, album_name, article_number, public_link)
                SELECT filename, album_name, article_number, public_link 
                FROM temp_files
                """, ())
            ]

            success = db_manager.execute_in_transaction_copy(operations, files_to_insert)

            elapsed = time.time() - start_time
            if success:
                logger.info(f"✅ Данные успешно сохранены в БД за {elapsed:.2f}s")
                return True
            else:
                logger.error(f"❌ Ошибка вставки в БД за {elapsed:.2f}s")
                return False

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
