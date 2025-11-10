# zip_processor.py
import os
import zipfile
import logging
from database import db_manager
from urllib.parse import quote
from utils import safe_folder_name, cleanup_album_thumbnails, cleanup_empty_folders


logger = logging.getLogger(__name__)

class ZipProcessor:
    def __init__(self, upload_folder, base_url, thumbnail_folder):
        self.upload_folder = upload_folder
        self.base_url = base_url
        self.thumbnail_folder = thumbnail_folder

    def process_zip(self, zip_path):
        """
        Обрабатывает ZIP-архив: извлекает изображения, создает структуру папок
        и обновляет базу данных.
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_basename = os.path.basename(zip_path)
                album_name_raw = os.path.splitext(zip_basename)[0]
                album_name = safe_folder_name(album_name_raw)
                album_path = os.path.join(self.upload_folder, album_name)

                # Очистка превью перед обработкой нового альбома
                cleanup_album_thumbnails(album_name, self.thumbnail_folder)

                # Создаем папку альбома если не существует
                os.makedirs(album_path, exist_ok=True)

                # Получаем список файлов заранее и фильтруем только изображения
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                image_files = [
                    file_info for file_info in zip_ref.infolist()
                    if not file_info.is_dir() and
                       os.path.splitext(file_info.filename.lower())[1] in allowed_extensions
                ]

                # Извлекаем только изображения, пропускаем служебные файлы
                zip_ref.extractall(album_path, members=image_files)

                files_to_insert = []

                # Проходим по извлеченным файлам
                for file_info in image_files:
                    original_file_path = os.path.join(album_path, file_info.filename)

                    # Проверяем что файл действительно существует после извлечения
                    if not os.path.exists(original_file_path):
                        continue

                    # Определяем артикул из пути файла в архиве
                    file_dir = os.path.dirname(file_info.filename)
                    if file_dir:
                        # Если файл в подпапке - используем имя папки как артикул
                        article_folder_raw = os.path.basename(file_dir)
                        article_folder_norm = safe_folder_name(article_folder_raw)

                        # Нормализуем имя папки если нужно
                        original_dir = os.path.dirname(original_file_path)
                        normalized_dir = os.path.join(os.path.dirname(original_dir), article_folder_norm)

                        if original_dir != normalized_dir:
                            os.makedirs(os.path.dirname(normalized_dir), exist_ok=True)
                            # Перемещаем файл в нормализованную папку
                            normalized_file_path = os.path.join(normalized_dir, os.path.basename(original_file_path))
                            os.rename(original_file_path, normalized_file_path)
                            original_file_path = normalized_file_path
                    else:
                        # Если файл в корне альбома - используем имя файла без расширения как артикул
                        article_folder_norm = safe_folder_name(
                            os.path.splitext(os.path.basename(original_file_path))[0])

                    # Вычисляем относительный путь
                    relative_file_path = os.path.relpath(original_file_path, self.upload_folder).replace(os.sep, '/')
                    encoded_path = quote(relative_file_path, safe='/')
                    public_link = f"{self.base_url}/images/{encoded_path}"

                    files_to_insert.append((
                        relative_file_path,
                        album_name,
                        article_folder_norm,
                        public_link
                    ))

                # Удаляем пустые папки которые могли остаться
                cleanup_empty_folders(album_path)

                # Используем одну транзакцию для всех операций
                operations = [
                    ("DELETE FROM files WHERE album_name = %s", (album_name,)),
                    ("""INSERT INTO files (filename, album_name, article_number, public_link) 
                        VALUES (%s, %s, %s, %s)""", files_to_insert, True)
                ]

                db_manager.execute_in_transaction(operations)

                logger.info(f"Processed ZIP {zip_path}: inserted {len(files_to_insert)} files")
                return True, album_name

        except Exception as e:
            logger.error(f"Error processing ZIP file {zip_path}: {e}")
            return False, str(e)

    def validate_zip_structure(self, zip_path):
        """
        Проверяет структуру ZIP-архива перед обработкой.
        Возвращает True если структура валидна, иначе False.
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Проверяем, что архив не пустой
                file_list = zip_ref.namelist()
                if not file_list:
                    logger.error("ZIP archive is empty")
                    return False

                # Проверяем наличие изображений
                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                has_images = any(
                    not info.is_dir() and
                    os.path.splitext(info.filename.lower())[1] in allowed_extensions
                    for info in zip_ref.infolist()
                )

                if not has_images:
                    logger.error("ZIP archive contains no valid images")
                    return False

                return True

        except zipfile.BadZipFile:
            logger.error("Invalid ZIP file format")
            return False
        except Exception as e:
            logger.error(f"Error validating ZIP structure: {e}")
            return False

    def get_zip_info(self, zip_path):
        """
        Возвращает информацию о содержимом ZIP-архива.
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                total_files = len(zip_ref.namelist())

                allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
                image_files = [
                    info for info in zip_ref.infolist()
                    if not info.is_dir() and
                       os.path.splitext(info.filename.lower())[1] in allowed_extensions
                ]

                total_size = sum(info.file_size for info in image_files)

                # Определяем структуру папок
                folders = set()
                for info in image_files:
                    dir_path = os.path.dirname(info.filename)
                    if dir_path:
                        folders.add(dir_path)

                return {
                    'total_files': total_files,
                    'image_files': len(image_files),
                    'total_size': total_size,
                    'folders': list(folders),
                    'album_name': safe_folder_name(os.path.splitext(os.path.basename(zip_path))[0])
                }

        except Exception as e:
            logger.error(f"Error getting ZIP info: {e}")
            return None
