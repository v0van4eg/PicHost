-- init.sql

-- Устанавливаем временную зону для всей базы данных
ALTER DATABASE pichosting SET timezone TO 'Europe/Moscow';

-- Таблица файлов
CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    album_name TEXT NOT NULL,
    article_number TEXT NOT NULL,
    public_link TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ОСНОВНЫЕ ИНДЕКСЫ
CREATE INDEX IF NOT EXISTS idx_files_album_name ON files(album_name);
CREATE INDEX IF NOT EXISTS idx_files_article_number ON files(article_number);
CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at);

-- ОПТИМИЗИРОВАННЫЕ СОСТАВНЫЕ ИНДЕКСЫ ДЛЯ ЧАСТЫХ ЗАПРОСОВ
CREATE INDEX IF NOT EXISTS idx_files_album_article ON files(album_name, article_number);
CREATE INDEX IF NOT EXISTS idx_files_album_created ON files(album_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_article_album ON files(article_number, album_name);

-- УНИКАЛЬНЫЙ ИНДЕКС ДЛЯ ПРЕДОТВРАЩЕНИЯ ДУБЛИКАТОВ
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_unique ON files(filename, album_name);

-- Таблица логов с оптимизированными индексами
CREATE TABLE IF NOT EXISTS user_actions_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_name TEXT,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ОПТИМИЗИРОВАННЫЕ ИНДЕКСЫ ДЛЯ ЛОГОВ
CREATE INDEX IF NOT EXISTS idx_user_actions_user_id ON user_actions_log(user_id);
CREATE INDEX IF NOT EXISTS idx_user_actions_timestamp ON user_actions_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_user_actions_composite ON user_actions_log(action, timestamp DESC);

-- Настройки для производительности (опционально)
ALTER TABLE files SET (fillfactor = 90);
ALTER TABLE user_actions_log SET (fillfactor = 85);
