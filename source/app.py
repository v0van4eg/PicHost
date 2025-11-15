# app.py

from auth_system import AuthManager, login_required, admin_required, role_required, auth_context_processor, \
    is_authenticated, get_current_user, permission_required, any_permission_required, Permissions
import os
from flask import Flask, request, session, jsonify, render_template, send_from_directory, send_file, current_app
import logging
from PIL import Image
import io
import hashlib
import shutil
import time
import tempfile
import atexit
from werkzeug.middleware.proxy_fix import ProxyFix

# Модули приложения
from utils import cleanup_album_thumbnails, log_user_action
from sync_manager import SyncManager
from database import db_manager as db_manager
from zip_processor import ZipProcessor
from document_generator import init_document_generator, get_document_generator


app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default_secret_key')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Инициализация аутентификации (теперь параметры берутся из переменных окружения)
auth_manager = AuthManager()
auth_manager.init_app(app)

# Сохраняем auth_manager в конфигурации приложения для доступа из декораторов
app.config['auth_manager'] = auth_manager

# Регистрация маршрутов аутентификации
auth_manager.register_routes()

# Добавление контекстного процессора
app.context_processor(auth_context_processor)

app.config['UPLOAD_FOLDER'] = 'images'
app.config['THUMBNAIL_FOLDER'] = 'thumbnails'
app.config['THUMBNAIL_SIZE'] = (96, 96)  # Размер превью
app.config['PREVIEW_SIZE'] = (600, 600)  # Размер для предпросмотра
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 * 1024  # 16GB

# Создаем папки если их нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)

# Логирование
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Конфигурация домена и базового URL получаем из переменных окружения
domain = os.environ.get('DOMAIN', 'pichosting.mooo.com')
base_url = f"http://{domain}"

###########  Инициализация модулей  ###############
document_generator = init_document_generator(base_url, app.config['UPLOAD_FOLDER'])

zip_processor = ZipProcessor(
    upload_folder=app.config['UPLOAD_FOLDER'],
    base_url=base_url,
    thumbnail_folder=app.config['THUMBNAIL_FOLDER'],
    max_workers=os.cpu_count()  # Используем все ядра
)

sync_manager = SyncManager(
    upload_folder=app.config['UPLOAD_FOLDER'],
    base_url=base_url,
    thumbnail_folder=app.config['THUMBNAIL_FOLDER']
)
###########  Инициализация модулей конец  ###############


def generate_image_hash(file_path):
    """Генерирует хэш для файла для кэширования"""
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.error(f"Error generating hash for {file_path}: {e}")
        return hashlib.md5(file_path.encode()).hexdigest()


def create_thumbnail(original_path, size, quality=85):
    """Создает миниатюру изображения"""
    try:
        with Image.open(original_path) as img:
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            img.thumbnail(size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, 'JPEG', quality=quality, optimize=True)
            buffer.seek(0)

            return buffer
    except Exception as e:
        logger.error(f"Error creating thumbnail for {original_path}: {e}")
        return None


def get_thumbnail_path(original_path, size):
    """Генерирует путь для миниатюры"""
    file_hash = generate_image_hash(original_path)
    filename = os.path.basename(original_path)
    name, ext = os.path.splitext(filename)
    size_str = f"{size[0]}x{size[1]}"

    rel_path = os.path.relpath(original_path, app.config['UPLOAD_FOLDER'])
    rel_dir = os.path.dirname(rel_path)

    thumbnail_filename = f"{name}_{size_str}_{file_hash[:8]}.jpg"

    if rel_dir and rel_dir != '.':
        thumbnail_dir = os.path.join(app.config['THUMBNAIL_FOLDER'], rel_dir)
        os.makedirs(thumbnail_dir, exist_ok=True)
        return os.path.join(thumbnail_dir, thumbnail_filename)
    else:
        return os.path.join(app.config['THUMBNAIL_FOLDER'], thumbnail_filename)


def cleanup_file_thumbnails(filename):
    """Очищает превью для конкретного файла"""
    try:
        original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(original_path):
            # Если оригинального файла нет, ищем и удаляем все возможные превью
            rel_dir = os.path.dirname(filename)
            file_base = os.path.splitext(os.path.basename(filename))[0]

            if rel_dir and rel_dir != '.':
                thumb_dir = os.path.join(app.config['THUMBNAIL_FOLDER'], rel_dir)
                if os.path.exists(thumb_dir):
                    # Удаляем все превью для этого файла
                    for thumb_file in os.listdir(thumb_dir):
                        if thumb_file.startswith(file_base + '_'):
                            thumb_path = os.path.join(thumb_dir, thumb_file)
                            os.remove(thumb_path)
                            logger.info(f"Deleted orphaned thumbnail: {thumb_path}")
        else:
            # Удаляем превью для существующего файла
            thumbnail_path = get_thumbnail_path(original_path, app.config['THUMBNAIL_SIZE'])
            preview_path = get_thumbnail_path(original_path, app.config['PREVIEW_SIZE'])

            for thumb_path in [thumbnail_path, preview_path]:
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
                    logger.info(f"Deleted thumbnail: {thumb_path}")

    except Exception as e:
        logger.error(f"Error cleaning up thumbnails for file {filename}: {e}")


# Инициализация базы данных
def init_db():
    """Инициализация базы данных при запуске приложения"""
    max_retries = 5
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            # Просто проверяем, что таблицы существуют
            result = db_manager.execute_query("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'files'
                );
            """, fetch=True)

            table_exists = result[0]['exists'] if result else False

            if not table_exists:
                logger.warning("Table 'files' does not exist. Database needs initialization.")
                # В продакшене таблицы должны создаваться через init.sql
                # Здесь просто логируем предупреждение

            logger.info("Database connection verified successfully")
            return

        except Exception as e:
            logger.warning(f"Database initialization attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to initialize database after {max_retries} attempts: {e}")
                raise


# Оптимизированное получение альбомов
def get_albums():
    # Используем составной индекс idx_files_album_article
    results = db_manager.execute_query("""
        SELECT DISTINCT album_name 
        FROM files 
        ORDER BY album_name
    """, fetch=True)
    return [album['album_name'] for album in results] if results else []

# Оптимизированное получение артикулов
def get_articles(album_name):
    # Используем составной индекс idx_files_album_article
    results = db_manager.execute_query(
        "SELECT DISTINCT article_number FROM files WHERE album_name = %s ORDER BY article_number",
        (album_name,),
        fetch=True
    )
    return [article['article_number'] for article in results] if results else []

# Оптимизированное получение файлов
def get_all_files():
    # Используем индекс по created_at
    results = db_manager.execute_query(
        """SELECT filename, album_name, article_number, public_link, created_at 
           FROM files 
           ORDER BY created_at DESC 
           LIMIT 1000""",  # Добавляем лимит для больших БД
        fetch=True
    )
    return results if results else []


# Эндпоинт синхронизации БД (обновленный)
@app.route('/api/sync', methods=['GET'])
@login_required
@permission_required(Permissions.SYNC_DATABASE)
def api_sync():
    try:
        deleted, added = sync_manager.sync()
        return jsonify({
            'message': 'Synchronization completed successfully',
            'deleted': deleted,
            'added': added
        })
    except Exception as e:
        logger.error(f"Error in sync endpoint: {e}")
        return jsonify({'error': f'Synchronization failed: {str(e)}'}), 500


# Новый эндпоинт для статистики синхронизации
@app.route('/api/sync/stats', methods=['GET'])
@login_required
@permission_required(Permissions.SYNC_DATABASE)
def api_sync_stats():
    """Возвращает статистику синхронизации"""
    try:
        stats = sync_manager.get_sync_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting sync stats: {e}")
        return jsonify({'error': str(e)}), 500


# Статус системы
@app.route('/api/stats')
@login_required
@permission_required(Permissions.VIEW_ALBUMS)
def api_stats():
    """Возвращает статистику дискового пространства"""
    try:
        import os
        import shutil

        # Статистика файлов в БД
        db_stats = db_manager.execute_query(
            "SELECT COUNT(*) as total_files FROM files",
            fetch=True
        )

        # Статистика по альбомам
        album_stats = db_manager.execute_query(
            "SELECT COUNT(DISTINCT album_name) as total_albums FROM files",
            fetch=True
        )

        disk_stats = {}

        # Проверяем различные возможные точки монтирования
        mount_points_to_check = [
            '/app/images',  # папка с изображениями в контейнере
            '/images',  # альтернативный путь
            '/'  # корневая файловая система как запасной вариант
        ]

        for mount_point in mount_points_to_check:
            try:
                # Используем shutil.disk_usage для получения статистики
                usage = shutil.disk_usage(mount_point)

                total = usage.total
                used = usage.used
                free = usage.free
                percent_used = (used / total) * 100 if total > 0 else 0

                # Определяем устройство/точку монтирования
                device_name = mount_point
                if mount_point == '/':
                    device_name = 'rootfs'
                elif mount_point == '/app/images':
                    device_name = 'storage'

                disk_stats[mount_point] = {
                    'total': total,
                    'used': used,
                    'free': free,
                    'percent_used': round(percent_used, 1),
                    'device': device_name
                }

                logger.info(f"✅ Получена статистика для {mount_point}: {percent_used:.1f}% использовано")
                break  # Используем первую доступную точку монтирования

            except (OSError, IOError, FileNotFoundError) as e:
                logger.debug(f"Не удалось получить статистику для {mount_point}: {e}")
                continue

        # Если ни одна точка монтирования не сработала, пробуем получить статистику для текущей рабочей директории
        if not disk_stats:
            try:
                current_dir = os.getcwd()
                usage = shutil.disk_usage(current_dir)

                total = usage.total
                used = usage.used
                free = usage.free
                percent_used = (used / total) * 100 if total > 0 else 0

                disk_stats[current_dir] = {
                    'total': total,
                    'used': used,
                    'free': free,
                    'percent_used': round(percent_used, 1),
                    'device': 'current_directory'
                }
                logger.info(f"✅ Используем статистику текущей директории: {current_dir}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить статистику диска: {e}")

        return jsonify({
            'disk_stats': disk_stats,
            'files': {
                'total_files': db_stats[0]['total_files'] if db_stats else 0,
                'total_albums': album_stats[0]['total_albums'] if album_stats else 0,
            },
            'status': 'success'
        })

    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return jsonify({
            'error': str(e),
            'status': 'error'
        }), 500


# --- Routes ---
@app.route('/')
def index():
    # Используем функцию из контекстного процессора
    if is_authenticated:
        # Определяем какой интерфейс показывать на основе прав
        user = get_current_user()
        logger.info(f"User authenticated: {user}")
        if user and auth_manager.user_has_permission(user, Permissions.UPLOAD_ZIP):
            # Пользователь может загружать - показываем полный интерфейс
            return render_template('index.html', base_url=base_url)
        else:
            # Только просмотр - показываем упрощенный интерфейс
            return render_template('index.html', base_url=base_url)
    else:
        return render_template('hello.html')


@app.route('/hello')
def hello():
    return render_template('hello.html', base_url=base_url)


# Эндпоинт для принудительной очистки превью альбома
@app.route('/api/cleanup-thumbnails/<album_name>', methods=['POST'])
@login_required
@permission_required(Permissions.MANAGE_ALBUMS)
def api_cleanup_thumbnails(album_name):
    """Принудительная очистка превью для альбома"""
    try:
        cleanup_album_thumbnails(album_name, app.config['THUMBNAIL_FOLDER'])
        return jsonify({'message': f'Thumbnails for album {album_name} cleaned up successfully'})
    except Exception as e:
        logger.error(f"Error cleaning up thumbnails for {album_name}: {e}")
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500


# Загрузка ZIP
@app.route('/upload', methods=['POST'])
@login_required
@permission_required(Permissions.UPLOAD_ZIP)
def upload_zip():
    logger.info("Upload endpoint called")
    if 'zipfile' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['zipfile']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file:
        original_name = file.filename

        # Обрабатываем прямо из памяти без сохранения на диск
        logger.info(f"💾 Обработка ZIP: {original_name}")
        process_start = time.time()

        # Создаем временный файл в памяти
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            success, result = zip_processor.process_zip(tmp_file.name, original_name)
            # Удаляем временный файл
            os.unlink(tmp_file.name)

        process_time = time.time() - process_start
        logger.info(f"✅ Обработка завершена за {process_time:.2f}s")

        if success:
            log_user_action('upload', 'album', original_name, {
                'album_name': result,
                'original_filename': original_name
            })
            return jsonify({'message': 'Files uploaded successfully', 'album_name': result})
        else:
            return jsonify({'error': f'Failed to process ZIP file: {result}'}), 500


# API: список всех файлов
@app.route('/api/files')
@login_required
@permission_required(Permissions.VIEW_FILES)
def api_files():
    logger.info("API files endpoint called")
    files = get_all_files()
    return jsonify(files)


# API: список альбомов
@app.route('/api/albums')
@login_required
@permission_required(Permissions.VIEW_ALBUMS)
def api_albums():
    logger.info("API albums endpoint called")
    albums = get_albums()
    return jsonify(albums)


# API: список артикулов для альбома
@app.route('/api/articles/<album_name>')
@login_required
@permission_required(Permissions.VIEW_ARTICLES)
def api_articles(album_name):
    logger.info(f"API articles endpoint called for album: {album_name}")
    articles = get_articles(album_name)
    return jsonify(articles)


# API: получение файлов для конкретного альбома (и опционально артикула)
@app.route('/api/files/<album_name>')
@app.route('/api/files/<album_name>/<article_name>')
@login_required
@permission_required(Permissions.VIEW_FILES)
def api_files_filtered(album_name, article_name=None):
    logger.info(f"API files filtered endpoint called for album: {album_name}, article: {article_name}")
    if article_name:
        results = db_manager.execute_query(
            "SELECT filename, album_name, article_number, public_link, created_at FROM files WHERE album_name = %s AND article_number = %s ORDER BY created_at DESC",
            (album_name, article_name),
            fetch=True
        )
    else:
        results = db_manager.execute_query(
            "SELECT filename, album_name, article_number, public_link, created_at FROM files WHERE album_name = %s ORDER BY created_at DESC",
            (album_name,),
            fetch=True
        )

    return jsonify(results if results else [])


# Новые эндпоинты для превью
@app.route('/api/thumbnails/<album_name>')
@app.route('/api/thumbnails/<album_name>/<article_name>')
@login_required
@permission_required(Permissions.VIEW_FILES)
def api_thumbnails(album_name, article_name=None):
    """API для получения информации о файлах с превью"""
    try:
        if article_name:
            results = db_manager.execute_query(
                """SELECT filename, album_name, article_number, public_link, created_at 
                   FROM files WHERE album_name = %s AND article_number = %s 
                   ORDER BY created_at DESC""",
                (album_name, article_name),
                fetch=True
            )
        else:
            results = db_manager.execute_query(
                """SELECT filename, album_name, article_number, public_link, created_at 
                   FROM files WHERE album_name = %s 
                   ORDER BY created_at DESC""",
                (album_name,),
                fetch=True
            )

        files_data = []
        if results:
            for row in results:
                filename = row['filename']
                album = row['album_name']
                article = row['article_number']
                public_link = row['public_link']
                created_at = row['created_at']

                original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                files_data.append({
                    'filename': filename,
                    'album_name': album,
                    'article_number': article,
                    'public_link': public_link,
                    'created_at': created_at,
                    'thumbnail_url': f"/thumbnails/small/{filename}",
                    'preview_url': f"/thumbnails/medium/{filename}",
                    'file_size': os.path.getsize(original_path) if os.path.exists(original_path) else 0
                })

        return jsonify(files_data)

    except Exception as e:
        logger.error(f"Error in api_thumbnails: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/thumbnails/small/<path:filename>')
@login_required
@permission_required(Permissions.VIEW_FILES)
def serve_small_thumbnail(filename):
    """Отдает маленькие превью (120x120)"""
    return serve_thumbnail(filename, app.config['THUMBNAIL_SIZE'])


@app.route('/thumbnails/medium/<path:filename>')
@login_required
@permission_required(Permissions.VIEW_FILES)
def serve_medium_thumbnail(filename):
    """Отдает средние превью (400x400)"""
    return serve_thumbnail(filename, app.config['PREVIEW_SIZE'])


def serve_thumbnail(filename, size):
    """Обслуживает миниатюры, создавая их при необходимости"""
    original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    if not os.path.exists(original_path):
        return jsonify({'error': 'File not found'}), 404

    thumbnail_path = get_thumbnail_path(original_path, size)

    # Создаем миниатюру если ее нет
    if not os.path.exists(thumbnail_path):
        thumbnail_buffer = create_thumbnail(original_path, size)
        if thumbnail_buffer:
            with open(thumbnail_path, 'wb') as f:
                f.write(thumbnail_buffer.getvalue())
            logger.info(f"Created new thumbnail: {thumbnail_path}")
        else:
            return send_from_directory('static', 'image-placeholder.png')

    return send_from_directory(os.path.dirname(thumbnail_path),
                               os.path.basename(thumbnail_path))


@app.route('/api/export-xlsx', methods=['POST'])
@login_required
@permission_required(Permissions.EXPORT_DATA)
def api_export_xlsx():
    """Создание XLSX документа с ссылками"""
    logger.info("API export XLSX endpoint called")
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        album_name = data.get('album_name')
        article_name = data.get('article_name')
        export_type = data.get('export_type', 'in_row')
        separator = data.get('separator', ', ')

        if not album_name or not export_type:
            return jsonify({'error': 'Missing required parameters'}), 400

        # Используем генератор документов
        temp_filename, download_filename = get_document_generator().generate_xlsx_export(
            album_name, article_name, export_type, separator
        )

        if temp_filename is None:
            return jsonify({'error': download_filename}), 500  # download_filename содержит сообщение об ошибке

        # Отправляем файл
        response = send_file(
            temp_filename,
            as_attachment=True,
            download_name=download_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        # Удаляем временный файл после отправки
        @response.call_on_close
        def remove_temp_file():
            try:
                os.unlink(temp_filename)
            except Exception as e:
                logger.error(f"Error removing temporary file {temp_filename}: {e}")

        return response

    except Exception as e:
        logger.error(f"Error creating XLSX file: {e}")
        return jsonify({'error': f'Failed to create XLSX file: {str(e)}'}), 500


##################################################
# Добавить новые эндпоинты для других форматов экспорта
@app.route('/api/export-csv', methods=['POST'])
@login_required
@permission_required(Permissions.EXPORT_DATA)
def api_export_csv():
    """Создание CSV документа с ссылками"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        album_name = data.get('album_name')
        article_name = data.get('article_name')
        separator = data.get('separator', ',')

        if not album_name:
            return jsonify({'error': 'Album name is required'}), 400

        temp_filename, download_filename = get_document_generator().generate_csv_export(
            album_name, article_name, separator
        )

        if temp_filename is None:
            return jsonify({'error': download_filename}), 500

        response = send_file(
            temp_filename,
            as_attachment=True,
            download_name=download_filename,
            mimetype='text/csv'
        )

        @response.call_on_close
        def remove_temp_file():
            try:
                os.unlink(temp_filename)
            except Exception as e:
                logger.error(f"Error removing temporary CSV file: {e}")

        return response

    except Exception as e:
        logger.error(f"Error creating CSV file: {e}")
        return jsonify({'error': f'Failed to create CSV file: {str(e)}'}), 500


@app.route('/api/export-text', methods=['POST'])
@login_required
@permission_required(Permissions.EXPORT_DATA)
def api_export_text():
    """Создание текстового документа со списком файлов"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        album_name = data.get('album_name')
        article_name = data.get('article_name')
        export_format = data.get('format', 'txt')  # 'txt' или 'md'

        if not album_name:
            return jsonify({'error': 'Album name is required'}), 400

        temp_filename, download_filename = get_document_generator().generate_file_list_export(
            album_name, article_name, export_format
        )

        if temp_filename is None:
            return jsonify({'error': download_filename}), 500

        mimetype = 'text/markdown' if export_format == 'md' else 'text/plain'

        response = send_file(
            temp_filename,
            as_attachment=True,
            download_name=download_filename,
            mimetype=mimetype
        )

        @response.call_on_close
        def remove_temp_file():
            try:
                os.unlink(temp_filename)
            except Exception as e:
                logger.error(f"Error removing temporary text file: {e}")

        return response

    except Exception as e:
        logger.error(f"Error creating text file: {e}")
        return jsonify({'error': f'Failed to create text file: {str(e)}'}), 500

    ##################################################


@app.route('/api/delete-album/<album_name>', methods=['DELETE'])
@login_required
@permission_required(Permissions.MANAGE_ALBUMS)
def api_delete_album(album_name):
    """Удаление альбома из БД и файловой системы"""
    logger.info(f"API delete album endpoint called for: {album_name}")
    try:
        # Получаем все файлы альбома
        files = db_manager.execute_query(
            "SELECT filename FROM files WHERE album_name = %s",
            (album_name,),
            fetch=True
        )
        filenames = [file['filename'] for file in files] if files else []

        # Удаляем записи из БД
        db_manager.execute_query(
            "DELETE FROM files WHERE album_name = %s",
            (album_name,),
            commit=True
        )

        # Удаляем файлы и папки
        album_path = os.path.join(app.config['UPLOAD_FOLDER'], album_name)
        thumbnail_album_path = os.path.join(app.config['THUMBNAIL_FOLDER'], album_name)

        # Удаляем файлы изображений
        if os.path.exists(album_path):
            shutil.rmtree(album_path)
            logger.info(f"Deleted album directory: {album_path}")

        # Удаляем превью альбома
        cleanup_album_thumbnails(album_name, app.config['THUMBNAIL_FOLDER'])

        # Удаляем папку превью если осталась
        if os.path.exists(thumbnail_album_path):
            shutil.rmtree(thumbnail_album_path)
            logger.info(f"Deleted album thumbnails directory: {thumbnail_album_path}")

        log_user_action('delete_album', 'album', album_name,
                        {'deleted_files_count': len(filenames) if 'filenames' in locals() else 'unknown'})
        return jsonify({'message': f'Альбом "{album_name}" успешно удален'})

    except Exception as e:
        logger.error(f"Error deleting album {album_name}: {e}")
        return jsonify({'error': f'Ошибка удаления альбома: {str(e)}'}), 500


@app.route('/api/delete-article/<album_name>/<article_name>', methods=['DELETE'])
@login_required
@permission_required(Permissions.MANAGE_ARTICLES)
def api_delete_article(album_name, article_name):
    """Удаление артикула из БД и файловой системы"""
    logger.info(f"API delete article endpoint called for: {album_name}/{article_name}")
    try:
        # Получаем все файлы артикула
        files = db_manager.execute_query(
            "SELECT filename FROM files WHERE album_name = %s AND article_number = %s",
            (album_name, article_name),
            fetch=True
        )
        filenames = [file['filename'] for file in files] if files else []

        # Удаляем записи из БД
        db_manager.execute_query(
            "DELETE FROM files WHERE album_name = %s AND article_number = %s",
            (album_name, article_name),
            commit=True
        )

        # Удаляем файлы и папки
        article_path = os.path.join(app.config['UPLOAD_FOLDER'], album_name, article_name)

        # Удаляем файлы изображений
        if os.path.exists(article_path):
            shutil.rmtree(article_path)
            logger.info(f"Deleted article directory: {article_path}")

        # Удаляем превью для каждого файла
        for filename in filenames:
            cleanup_file_thumbnails(filename)

        # Удаляем папку превью артикула если осталась
        thumbnail_article_path = os.path.join(app.config['THUMBNAIL_FOLDER'], album_name, article_name)
        if os.path.exists(thumbnail_article_path):
            shutil.rmtree(thumbnail_article_path)
            logger.info(f"Deleted article thumbnails directory: {thumbnail_article_path}")

        # Синхронизируем БД после удаления
        # sync_manager.sync()
        log_user_action('delete_article', 'article', f"{album_name}/{article_name}",
                        {'deleted_files_count': len(filenames) if 'filenames' in locals() else 'unknown'})
        return jsonify({'message': f'Артикул "{article_name}" в альбоме "{album_name}" успешно удален'})

    except Exception as e:
        logger.error(f"Error deleting article {article_name} from album {album_name}: {e}")
        return jsonify({'error': f'Ошибка удаления артикула: {str(e)}'}), 500


# API: количество файлов в альбоме
@app.route('/api/count/album/<album_name>')
@login_required
@permission_required(Permissions.VIEW_ALBUMS)
def api_count_album(album_name):
    """Возвращает количество файлов в альбоме"""
    logger.info(f"API count album endpoint called for: {album_name}")
    try:
        result = db_manager.execute_query(
            "SELECT COUNT(*) as count FROM files WHERE album_name = %s",
            (album_name,),
            fetch=True
        )
        count = result[0]['count'] if result else 0
        logger.info(f"Album {album_name} has {count} files")
        return jsonify({'count': count})
    except Exception as e:
        logger.error(f"Error counting files for album {album_name}: {e}")
        return jsonify({'error': str(e)}), 500


# API: количество файлов в артикуле
@app.route('/api/count/article/<album_name>/<article_name>')
@login_required
@permission_required(Permissions.VIEW_ARTICLES)
def api_count_article(album_name, article_name):
    """Возвращает количество файлов в артикуле"""
    logger.info(f"API count article endpoint called for: {album_name}/{article_name}")
    try:
        result = db_manager.execute_query(
            "SELECT COUNT(*) as count FROM files WHERE album_name = %s AND article_number = %s",
            (album_name, article_name),
            fetch=True
        )
        count = result[0]['count'] if result else 0
        logger.info(f"Article {article_name} in album {album_name} has {count} files")
        return jsonify({'count': count})
    except Exception as e:
        logger.error(f"Error counting files for article {article_name} in album {album_name}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin')
@login_required
@permission_required(Permissions.ACCESS_ADMIN)
def admin_panel():
    logger.info("Admin panel accessed")
    user = session.get('user', {})
    display_roles = user.get('display_roles', [])
    all_roles = user.get('roles', [])
    return render_template('admin.html', display_roles=display_roles, all_roles=all_roles)


@app.route('/admin/logs')
@login_required
@permission_required(Permissions.VIEW_LOGS)
def admin_logs():
    """Страница с логами действий пользователей"""
    logger.info("Admin logs accessed")
    page = request.args.get('page', 1, type=int)
    per_page = 50  # Количество записей на странице
    offset = (page - 1) * per_page

    search_user = request.args.get('search_user', '')
    search_action = request.args.get('search_action', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Формируем условия для фильтрации
    conditions = []
    params = []

    if search_user:
        conditions.append("username ILIKE %s")  # ILIKE для нечувствительного к регистру поиска
        params.append(f"%{search_user}%")
    if search_action:
        conditions.append("action = %s")
        params.append(search_action)
    if date_from:
        conditions.append("timestamp >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp <= %s")
        params.append(date_to)

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_clause = " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
    params.extend([per_page, offset])

    query = f"""
    SELECT user_id, username, action, resource_type, resource_name, details, timestamp
    FROM user_actions_log
    {where_clause}
    {order_clause}
    """

    try:
        logs = db_manager.execute_query(query, tuple(params), fetch=True)
        # Получаем общее количество записей для пагинации
        count_query = f"SELECT COUNT(*) as total FROM user_actions_log {where_clause}"
        total_count_result = db_manager.execute_query(count_query, tuple(params[:-2]),
                                                      fetch=True)  # Исключаем LIMIT и OFFSET
        total_count = total_count_result[0]['total'] if total_count_result else 0
    except Exception as e:
        logger.error(f"Error fetching logs: {e}")
        logs = []
        total_count = 0

    # Получаем уникальные действия для фильтра
    try:
        actions_query = "SELECT DISTINCT action FROM user_actions_log ORDER BY action"
        actions = db_manager.execute_query(actions_query, fetch=True)
        action_list = [row['action'] for row in actions]
    except Exception as e:
        logger.error(f"Error fetching actions for filter: {e}")
        action_list = []

    return render_template('logs.html',
                           logs=logs,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           search_user=search_user,
                           search_action=search_action,
                           date_from=date_from,
                           date_to=date_to,
                           available_actions=action_list,
                           current_user=get_current_user())  # Передаем пользователя в шаблон


# Инициализация базы данных при запуске приложения
init_db()


# Функция для закрытия соединений при выходе
@atexit.register
def cleanup():
    db_manager.close()


# --- Main ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, ssl_context='adhoc')
