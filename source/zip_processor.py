import os
import zipfile
import logging
import time
import threading
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from database import db_manager
from urllib.parse import quote
from utils import safe_folder_name, cleanup_album_thumbnails, cleanup_empty_folders

logger = logging.getLogger(__name__)


class ZipProcessor:
    def __init__(self, upload_folder, base_url, thumbnail_folder, max_workers=None):
        self.upload_folder = upload_folder
        self.base_url = base_url
        self.thumbnail_folder = thumbnail_folder
        # Ограничиваем количество воркеров для стабильности
        self.max_workers = min(max_workers or os.cpu_count(), 8)
        self.processing_lock = threading.Lock()
        self.active_processes = {}
        self.batch_size = 50
        self.allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
        self.system_folders = {'__macosx', '.ds_store', 'thumbs.db', '.thumbnails', 'thumbs'}

    def process_zip(self, zip_path, original_zip_name=None):
        """Основной метод обработки ZIP с мультипроцессингом"""
        return self.process_zip_multiprocessing(zip_path, original_zip_name)

    def process_zip_multiprocessing(self, zip_path, original_zip_name=None):
        """Обработка ZIP с использованием ProcessPoolExecutor"""
        logger.info(f"🚀 Начинаем многопроцессорную обработку ZIP: {zip_path}")
        start_time = time.time()

        zip_basename = os.path.basename(zip_path)
        with self.processing_lock:
            if zip_basename in self.active_processes:
                return False, "ZIP уже обрабатывается"
            self.active_processes[zip_basename] = True

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Определяем имя альбома
                album_name = self._get_album_name_from_zip(zip_ref, original_zip_name)
                album_path = os.path.join(self.upload_folder, album_name)

                # Валидация структуры архива
                is_valid, validation_error = self._validate_zip_structure(zip_ref)
                if not is_valid:
                    return False, validation_error

                # Очистка превью и создание папки альбома
                cleanup_album_thumbnails(album_name, self.thumbnail_folder)
                os.makedirs(album_path, exist_ok=True)

                # Получаем ТОЛЬКО изображения для обработки
                image_files = self._get_image_files_with_paths(zip_ref)
                if not image_files:
                    return False, "Нет изображений для обработки"

                logger.info(f"📁 Альбом: '{album_name}', изображений: {len(image_files)}")

                # Мультипроцессорная обработка ТОЛЬКО изображений
                files_to_insert = self._process_files_multiprocessing(
                    zip_ref, image_files, album_path, album_name
                )

                if not files_to_insert:
                    return False, "Не удалось обработать изображения"

                # Удаляем пустые папки
                cleanup_empty_folders(album_path)

                # Батч-вставка в БД с обработкой дубликатов
                db_success = self._batch_db_insert_safe(album_name, files_to_insert)

                processing_time = time.time() - start_time
                logger.info(f"✅ ZIP обработан за {processing_time:.2f}s: {len(files_to_insert)} изображений")

                return db_success, album_name

        except Exception as e:
            logger.error(f"❌ Ошибка обработки ZIP {zip_path}: {e}")
            return False, str(e)
        finally:
            with self.processing_lock:
                self.active_processes.pop(zip_basename, None)

    def _get_album_name_from_zip(self, zip_ref, original_zip_name=None):
        """Определяет имя альбома"""
        if original_zip_name:
            zip_name_without_ext = os.path.splitext(original_zip_name)[0]
            logger.info(f"📁 Используем оригинальное имя ZIP как альбом: {zip_name_without_ext}")
            return safe_folder_name(zip_name_without_ext)

        # Пытаемся определить из структуры архива
        try:
            all_files = [f.filename for f in zip_ref.filelist if not f.is_dir()]
            if not all_files:
                return safe_folder_name("unnamed_album")

            # Анализируем структуру папок
            folder_structure = {}
            for file_path in all_files:
                parts = file_path.split('/')
                if len(parts) > 1:
                    album_name = parts[0]
                    if album_name not in folder_structure:
                        folder_structure[album_name] = set()
                    if len(parts) >= 3:
                        article_name = parts[1]
                        folder_structure[album_name].add(article_name)

            # Если есть только одна папка верхнего уровня - используем ее как альбом
            if len(folder_structure) == 1:
                album_name = list(folder_structure.keys())[0]
                if not self._is_system_folder(album_name):
                    logger.info(f"🎯 Используем имя альбома из структуры: {album_name}")
                    return safe_folder_name(album_name)

        except Exception as e:
            logger.warning(f"Не удалось определить альбом из структуры: {e}")

        # Fallback
        return safe_folder_name("unnamed_album")

    def _is_system_folder(self, folder_name):
        """Проверяет, является ли папка системной"""
        return folder_name.lower() in self.system_folders

    def _get_image_files_with_paths(self, zip_ref):
        """Получает только изображения с их путями в архиве"""
        image_files = []

        for file_info in zip_ref.infolist():
            if file_info.is_dir():
                continue

            filename = file_info.filename

            # Пропускаем системные файлы и папки
            if any(part.lower() in self.system_folders for part in filename.split('/')):
                continue
            if any(part.lower().startswith('__') for part in filename.split('/')):
                continue
            if any(part.lower().startswith('.') for part in filename.split('/')):
                continue

            # Проверяем расширение
            _, ext = os.path.splitext(filename.lower())
            if ext in self.allowed_extensions:
                image_files.append((filename, file_info))

        return image_files

    def _process_files_multiprocessing(self, zip_ref, image_files, album_path, album_name):
        """Мультипроцессорная обработка только изображений"""
        files_to_insert = []

        # Создаем временную папку для извлечения
        temp_extract_dir = os.path.join(self.upload_folder, f"temp_extract_{int(time.time())}")
        os.makedirs(temp_extract_dir, exist_ok=True)

        try:
            # Извлекаем ТОЛЬКО изображения
            logger.info("📦 Извлекаем изображения из архива...")
            extracted_files = []

            for filename, file_info in image_files:
                try:
                    # Извлекаем файл
                    zip_ref.extract(file_info, temp_extract_dir)
                    full_path = os.path.join(temp_extract_dir, filename)

                    if os.path.exists(full_path):
                        extracted_files.append((full_path, filename))
                    else:
                        logger.warning(f"Файл не извлекся: {filename}")

                except Exception as e:
                    logger.error(f"Ошибка извлечения {filename}: {e}")

            logger.info(f"📁 Извлечено {len(extracted_files)} изображений")

            # Обрабатываем файлы процессами
            batch_size = min(self.batch_size, max(10, len(extracted_files) // self.max_workers))
            batches = [extracted_files[i:i + batch_size] for i in range(0, len(extracted_files), batch_size)]

            logger.info(f"🔄 Обрабатываем {len(batches)} батчей по {batch_size} файлов")

            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_batch = {}

                for i, batch in enumerate(batches):
                    future = executor.submit(
                        self._process_image_batch_multiprocessing,
                        batch, album_path, album_name, self.base_url, i
                    )
                    future_to_batch[future] = i

                # Собираем результаты
                for future in as_completed(future_to_batch):
                    try:
                        batch_results = future.result(timeout=300)
                        files_to_insert.extend(batch_results)
                        batch_num = future_to_batch[future]
                        processed_count = len(batch_results)
                        logger.info(f"✅ Батч {batch_num + 1}/{len(batches)} обработан: {processed_count} файлов")
                    except Exception as e:
                        logger.error(f"❌ Ошибка обработки батча: {e}")

        finally:
            # Очищаем временную папку
            try:
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Не удалось очистить временную папку: {e}")

        return files_to_insert

    @staticmethod
    def _process_image_batch_multiprocessing(file_batch, album_path, album_name, base_url, batch_num):
        """Статический метод для обработки батча изображений в отдельном процессе"""
        import shutil
        import os
        from urllib.parse import quote
        from utils import safe_folder_name

        batch_results = []

        for file_path, original_filename in file_batch:
            try:
                # Пропускаем системные файлы еще раз для надежности
                if any(part.lower() in {'__macosx', '.ds_store', 'thumbs.db', '.thumbnails', 'thumbs'}
                       for part in original_filename.split('/')):
                    continue

                # Определяем структуру папок из оригинального пути
                path_parts = original_filename.split('/')

                if len(path_parts) > 1:
                    # Есть вложенные папки - используем их для структуры
                    article_name = safe_folder_name(path_parts[-2]) if len(path_parts) >= 2 else safe_folder_name(
                        os.path.splitext(path_parts[-1])[0])
                    target_filename = path_parts[-1]

                    # Создаем целевую структуру папок
                    relative_dir = os.path.join(album_name, *path_parts[:-1])
                    target_dir = os.path.join(os.path.dirname(album_path), relative_dir)
                else:
                    # Файл в корне архива
                    article_name = safe_folder_name(os.path.splitext(original_filename)[0])
                    target_filename = original_filename
                    relative_dir = album_name
                    target_dir = album_path

                # Создаем папку назначения
                os.makedirs(target_dir, exist_ok=True)

                # Целевой путь для файла
                target_path = os.path.join(target_dir, target_filename)

                # Перемещаем файл
                shutil.move(file_path, target_path)

                # Относительный путь от upload_folder
                final_rel_path = os.path.relpath(target_path, os.path.dirname(album_path))

                # Создаем публичную ссылку
                encoded_path = quote(final_rel_path.replace(os.sep, '/'), safe='/')
                public_link = f"{base_url}/images/{encoded_path}"

                result = (
                    final_rel_path.replace(os.sep, '/'),
                    album_name,
                    article_name,
                    public_link
                )
                batch_results.append(result)

            except Exception as e:
                print(f"Ошибка обработки файла {original_filename}: {e}")

        return batch_results

    def _batch_db_insert_safe(self, album_name, files_to_insert):
        """Безопасная вставка с обработкой дубликатов"""
        try:
            if not files_to_insert:
                return True

            logger.info(f"💾 Безопасная вставка {len(files_to_insert)} записей")
            start_time = time.time()

            # Удаляем старые записи этого альбома
            delete_success = self._cleanup_album_before_insert(album_name)
            if not delete_success:
                logger.error("Не удалось очистить старые записи альбома")
                return False

            # Вставляем новые записи
            insert_success = self._insert_files_batch(files_to_insert)

            elapsed = time.time() - start_time
            if insert_success:
                logger.info(f"✅ Данные вставлены за {elapsed:.2f}s ({len(files_to_insert) / elapsed:.1f} записей/сек)")
                return True
            else:
                logger.error(f"❌ Ошибка вставки за {elapsed:.2f}s")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка безопасной вставки: {e}")
            return False

    def _cleanup_album_before_insert(self, album_name):
        """Очищает записи альбома перед вставкой"""
        try:
            result = db_manager.execute_query(
                "DELETE FROM files WHERE album_name = %s",
                (album_name,),
                commit=True
            )
            logger.info(f"🗑️ Удалены старые записи альбома: {album_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления старых записей: {e}")
            return False

    def _insert_files_batch(self, files_to_insert):
        """Вставляет батч файлов"""
        try:
            # Подготавливаем данные
            filenames = [f[0] for f in files_to_insert]
            album_names = [f[1] for f in files_to_insert]
            article_numbers = [f[2] for f in files_to_insert]
            public_links = [f[3] for f in files_to_insert]

            operations = [
                # Массовая вставка
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
            return success

        except Exception as e:
            logger.error(f"❌ Ошибка вставки батча: {e}")
            return False

    def _validate_zip_structure(self, zip_ref):
        """Валидация структуры архива"""
        try:
            all_files = [f.filename for f in zip_ref.filelist if not f.is_dir()]

            if not all_files:
                return False, "ZIP архив пуст"

            # Проверяем допустимые расширения
            valid_files = 0

            for file_path in all_files:
                # Пропускаем системные файлы
                if any(part.lower() in self.system_folders for part in file_path.split('/')):
                    continue
                if any(part.lower().startswith('__') for part in file_path.split('/')):
                    continue
                if any(part.lower().startswith('.') for part in file_path.split('/')):
                    continue

                _, ext = os.path.splitext(file_path.lower())
                if ext in self.allowed_extensions:
                    valid_files += 1

            if valid_files == 0:
                return False, "ZIP архив не содержит валидных изображений"

            logger.info(f"✅ Структура архива проверена: {len(all_files)} файлов, {valid_files} изображений")
            return True, None

        except Exception as e:
            logger.error(f"Error validating ZIP structure: {e}")
            return False, str(e)

    def get_processing_stats(self):
        """Статистика обработки"""
        return {
            'active_processes': len(self.active_processes),
            'max_workers': self.max_workers,
            'batch_size': self.batch_size
        }
