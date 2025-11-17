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


    def process_zip(self, zip_path, original_zip_name=None):
        """
        Основной метод обработки ZIP
        """
        return self.process_zip_fast(zip_path, original_zip_name)

    def _extract_album_structure(self, zip_ref):
        """
        Анализирует структуру ZIP архива и определяет правильное имя альбома
        и структуру папок
        """
        try:
            # Получаем все файлы в архиве
            all_files = [f.filename for f in zip_ref.filelist if not f.is_dir()]

            if not all_files:
                return None, "ZIP архив пуст"

            # Анализируем структуру папок
            folder_structure = {}
            root_files = []

            for file_path in all_files:
                parts = file_path.split('/')

                # Убираем пустые части пути
                parts = [p for p in parts if p]

                # Если файл в корне архива
                if len(parts) == 1:
                    root_files.append(file_path)
                    continue

                # Первая папка - это потенциальный альбом
                album_name = parts[0]
                if album_name not in folder_structure:
                    folder_structure[album_name] = set()

                # Если есть вторая папка - это артикул
                if len(parts) >= 3:
                    article_name = parts[1]
                    folder_structure[album_name].add(article_name)

            # Если есть только одна папка верхнего уровня и нет файлов в корне - используем ее как альбом
            if len(folder_structure) == 1 and not root_files:
                album_name = list(folder_structure.keys())[0]
                # Проверяем, что это не служебная папка
                if not self._is_system_folder(album_name):
                    return safe_folder_name(album_name), None

            # Если файлы в корне или несколько папок верхнего уровня
            return None, "Файлы в корне архива или сложная структура"

        except Exception as e:
            logger.error(f"Error analyzing ZIP structure: {e}")
            return None, str(e)


    def _is_system_folder(self, folder_name):
        """
        Проверяет, является ли папка системной (например, __MACOSX)
        """
        system_folders = {'__macosx', '.ds_store', 'thumbs.db', '.thumbnails'}
        return folder_name.lower() in system_folders

    def _get_album_name_from_zip(self, zip_path, zip_ref, original_zip_name=None):
        """
        Определяет имя альбома из структуры ZIP архива
        """
        # Пытаемся определить имя альбома из структуры
        album_name, structure_error = self._extract_album_structure(zip_ref)

        if album_name and album_name != "root_album":
            logger.info(f"🎯 Используем имя альбома из структуры: {album_name}")
            # Если определили из структуры, используем безопасное имя
            return safe_folder_name(album_name)

        # Если не удалось определить из структуры, используем оригинальное имя ZIP
        if original_zip_name:
            zip_name_without_ext = os.path.splitext(original_zip_name)[0]
            logger.info(f"📁 Используем оригинальное имя ZIP как альбом: {zip_name_without_ext}")
            return safe_folder_name(zip_name_without_ext)

        # Fallback: используем имя временного файла (без расширения .zip)
        zip_basename = os.path.basename(zip_path)
        zip_name_without_ext = os.path.splitext(zip_basename)[0]
        logger.warning(f"⚠️ Используем временное имя как альбом: {zip_name_without_ext}")
        return safe_folder_name(zip_name_without_ext)


    def _validate_zip_structure(self, zip_ref):
        """
        Проверяет структуру ZIP архива
        """
        try:
            all_files = [f.filename for f in zip_ref.filelist if not f.is_dir()]

            if not all_files:
                return False, "ZIP архив не содержит файлов"

            # Проверяем, что все файлы находятся в папках
            root_files = [f for f in all_files if '/' not in f]
            if root_files:
                logger.warning(f"⚠️ В архиве найдены файлы в корне: {len(root_files)} файлов")

            # Проверяем допустимые расширения
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
            valid_files = 0

            for file_path in all_files:
                # Пропускаем системные файлы
                if any(part.lower().startswith('__') for part in file_path.split('/')):
                    continue

                _, ext = os.path.splitext(file_path.lower())
                if ext in allowed_extensions:
                    valid_files += 1

            if valid_files == 0:
                return False, "ZIP архив не содержит валидных изображений"

            logger.info(f"✅ Структура архива проверена: {len(all_files)} файлов, {valid_files} изображений")
            return True, None

        except Exception as e:
            logger.error(f"Error validating ZIP structure: {e}")
            return False, str(e)

    def process_zip_fast(self, zip_path, original_zip_name=None):
        """
        Оптимизированная обработка ZIP с правильным определением структуры
        """
        logger.info(f"🚀 Начинаем обработку ZIP: {zip_path}")
        logger.info(f"📦 Оригинальное имя ZIP: {original_zip_name}")
        start_time = time.time()

        zip_basename = os.path.basename(zip_path)
        with self.processing_lock:
            if zip_basename in self.active_processes:
                return False, "ZIP уже обрабатывается"
            self.active_processes[zip_basename] = True

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Определяем имя альбома из структуры архива
                album_name = self._get_album_name_from_zip(zip_path, zip_ref, original_zip_name)
                album_path = os.path.join(self.upload_folder, album_name)

                # Валидация структуры архива
                is_valid, validation_error = self._validate_zip_structure(zip_ref)
                if not is_valid:
                    return False, validation_error

                # Очистка превью
                cleanup_album_thumbnails(album_name, self.thumbnail_folder)
                os.makedirs(album_path, exist_ok=True)

                # Получаем список файлов для обработки
                image_files = self._get_image_files(zip_ref)

                if not image_files:
                    return False, "Нет файлов для обработки"

                logger.info(f"📁 Альбом: '{album_name}', файлов: {len(image_files)}")

                # Параллельная обработка с батчингом
                files_to_insert = self._process_files_parallel_batch(zip_ref, image_files, album_path, album_name)

                if not files_to_insert:
                    return False, "Не удалось обработать файлы"

                # Удаляем пустые папки
                cleanup_empty_folders(album_path)

                # Батч-вставка в БД
                db_success = self._batch_db_insert_fast(album_name, files_to_insert)

                processing_time = time.time() - start_time
                logger.info(
                    f"✅ ZIP обработан за {processing_time:.2f}s: {len(files_to_insert)} файлов в альбоме '{album_name}'")


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

        valid_files = []
        for file_info in zip_ref.infolist():
            if file_info.is_dir():
                continue

            # Пропускаем системные файлы и папки
            if any(part.lower().startswith('__') for part in file_info.filename.split('/')):
                continue

            ext = os.path.splitext(file_info.filename.lower())[1]
            if ext in allowed_extensions:
                valid_files.append(file_info)

        return valid_files

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
                # Пропускаем системные файлы
                if any(part.lower().startswith('__') for part in file_info.filename.split('/')):
                    continue

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
        """Быстрая обработка одного файла с правильным определением структуры"""
        try:
            # Используем относительный путь как ключ кэша
            relative_path = os.path.relpath(file_path, self.upload_folder)
            cache_key = f"{album_name}_{relative_path}"

            if cache_key in self.path_cache:
                return self.path_cache[cache_key]

            file_dir = os.path.dirname(relative_path)
            filename = os.path.basename(relative_path)

            # Определяем артикул из структуры пути
            article_number = None

            if file_dir and file_dir != '.':
                # Путь: temp_extract/album_name/article_number/filename
                # ИЛИ: album_name/article_number/filename
                path_parts = file_dir.split(os.sep)

                # Если путь содержит больше 1 части, значит есть вложенные папки
                if len(path_parts) >= 2:
                    # Последняя часть пути - это артикул
                    article_number = safe_folder_name(path_parts[-1])

                    # Нормализуем путь: перемещаем файл из временной структуры в финальную
                    normalized_dir = os.path.join(self.upload_folder, album_name, article_number)
                    normalized_path = os.path.join(normalized_dir, filename)

                    # Создаем целевую директорию и перемещаем файл
                    os.makedirs(normalized_dir, exist_ok=True)
                    if file_path != normalized_path:
                        shutil.move(file_path, normalized_path)
                        relative_path = os.path.relpath(normalized_path, self.upload_folder)
                else:
                    # Файл находится прямо в папке альбома (без артикула)
                    article_number = safe_folder_name(os.path.splitext(filename)[0])
            else:
                # Файл в корне временной папки извлечения
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

    def _quick_validate_zip(self, zip_ref):
        """Быстрая валидация ZIP архива"""
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}

        # Проверяем первые 10 файлов для быстрой валидации
        for file_info in zip_ref.infolist()[:10]:
            if not file_info.is_dir():
                # Пропускаем системные файлы
                if any(part.lower().startswith('__') for part in file_info.filename.split('/')):
                    continue

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
