-- init.sql

-- Существующие таблицы...
CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    album_name TEXT NOT NULL,
    article_number TEXT NOT NULL,
    public_link TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_album_name ON files(album_name);
CREATE INDEX IF NOT EXISTS idx_files_article_number ON files(article_number);
CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at);

-- Добавляем комментарий к таблице
COMMENT ON TABLE files IS 'Table for storing image file information';

-- Новая таблица для журналирования действий пользователей
CREATE TABLE IF NOT EXISTS user_actions_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT, -- Используем sub (subject) из OIDC
    username TEXT NOT NULL, -- Имя пользователя (например, preferred_username)
    action TEXT NOT NULL, -- Тип действия (например, 'upload', 'delete_album', 'delete_article')
    resource_type TEXT, -- Тип ресурса ('file', 'album', 'article')
    resource_name TEXT, -- Имя ресурса (например, имя альбома или артикула)
    details JSONB, -- Дополнительные детали в формате JSON (например, список удаленных файлов)
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Время действия
);

-- Индекс для быстрой выборки по времени
CREATE INDEX IF NOT EXISTS idx_user_actions_log_timestamp ON user_actions_log(timestamp);

-- Комментарий к таблице
COMMENT ON TABLE user_actions_log IS 'Log of user actions for audit and monitoring';
