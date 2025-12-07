"""Модуль для работы с метриками приложения"""

import os
import shutil
import psutil
from datetime import datetime
from prometheus_client import Gauge, generate_latest, CollectorRegistry, multiprocess
import logging
from database import db_manager

logger = logging.getLogger(__name__)

# Определение метрик Prometheus
ACTIVE_CONNECTIONS = Gauge(
    'active_connections',
    'Number of active connections'
)

ALBUM_COUNT = Gauge(
    'album_count',
    'Number of albums'
)

ARTICLE_COUNT = Gauge(
    'article_count',
    'Number of articles'
)

FILE_COUNT = Gauge(
    'file_count',
    'Number of files'
)

DISK_USAGE_TOTAL = Gauge(
    'disk_usage_bytes_total',
    'Total disk space in bytes',
    ['path']
)

DISK_USAGE_FREE = Gauge(
    'disk_usage_bytes_free',
    'Free disk space in bytes',
    ['path']
)

DISK_USAGE_USED = Gauge(
    'disk_usage_bytes_used',
    'Used disk space in bytes',
    ['path']
)

DB_SIZE = Gauge(
    'database_size_bytes',
    'Database size in bytes'
)

UPTIME = Gauge(
    'application_uptime_seconds',
    'Application uptime in seconds'
)

# Метрики использования памяти
MEMORY_TOTAL = Gauge('memory_bytes_total', 'Total physical memory in bytes')
MEMORY_USED = Gauge('memory_bytes_used', 'Used physical memory in bytes')
MEMORY_FREE = Gauge('memory_bytes_free', 'Free physical memory in bytes')
MEMORY_PERCENT = Gauge('memory_percent_used', 'Percentage of used memory')


def update_metrics(start_time=None):
    """Обновление метрик на основе текущего состояния системы. 
    Вызывается при запросе к /metrics"""
    try:
        # Обновление числа альбомов
        albums_result = db_manager.execute_query(
            "SELECT COUNT(DISTINCT album_name) as total_albums FROM files",
            fetch=True
        )
        total_albums = albums_result[0]['total_albums'] if albums_result else 0
        ALBUM_COUNT.set(total_albums)

        # Обновление числа артикулов
        articles_result = db_manager.execute_query(
            "SELECT COUNT(DISTINCT article_number) as total_articles FROM files",
            fetch=True
        )
        total_articles = articles_result[0]['total_articles'] if articles_result else 0
        ARTICLE_COUNT.set(total_articles)

        # Обновление числа файлов
        files_result = db_manager.execute_query(
            "SELECT COUNT(*) as total_files FROM files",
            fetch=True
        )
        total_files = files_result[0]['total_files'] if files_result else 0
        FILE_COUNT.set(total_files)

        # Обновление статистики дискового пространства
        # Проверяем различные возможные точки монтирования
        mount_points_to_check = [
            '/app/images',  # папка с изображениями в контейнере
            '/images',  # альтернативный путь
            '/'  # корневая файловая система как запасной вариант
        ]

        for mount_point in mount_points_to_check:
            try:
                usage = shutil.disk_usage(mount_point)
                total = usage.total
                used = usage.used
                free = usage.free

                DISK_USAGE_TOTAL.labels(path=mount_point).set(total)
                DISK_USAGE_USED.labels(path=mount_point).set(used)
                DISK_USAGE_FREE.labels(path=mount_point).set(free)
                break
            except (OSError, IOError, FileNotFoundError):
                continue

        # Обновление размера базы данных
        db_size_result = db_manager.execute_query(
            "SELECT pg_database_size(current_database()) as db_size",
            fetch=True
        )
        if db_size_result:
            db_size_bytes = db_size_result[0]['db_size']
            DB_SIZE.set(db_size_bytes)

        # Обновление времени работы приложения, если передано время запуска
        if start_time:
            uptime = (datetime.now() - start_time).total_seconds()
            UPTIME.set(uptime)

        # Обновление числа активных подключений (примерное значение)
        # В реальном приложении это может быть сложнее реализовать, поэтому пока ставим 0
        ACTIVE_CONNECTIONS.set(0)

        # Обновление метрик памяти
        mem = psutil.virtual_memory()
        MEMORY_TOTAL.set(mem.total)
        MEMORY_USED.set(mem.used)
        MEMORY_FREE.set(mem.available)  # mem.free в Linux почти всегда мало; available — более точное "свободно"
        MEMORY_PERCENT.set(mem.percent)

    except Exception as e:
        logger.error(f"Error updating metrics: {e}")
