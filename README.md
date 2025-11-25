# PicHost --- self-hosted сервис для хранения и публикации изображений

PicHost --- веб‑приложение на Flask для хранения, каталогизации,
предпросмотра и массовой загрузки изображений. Поддерживает Keycloak,
права доступа, ZIP‑импорт, предпросмотр, экспорт XLSX/CSV и многое
другое.

## Возможности

-   OAuth2/OpenID Connect через Keycloak\
-   Роли и пермишены (viewer/user/admin)\
-   Массовая загрузка ZIP\
-   Автогенерация миниатюр\
-   Админ‑панель, логи, статистика\
-   Экспорт XLSX/CSV\
-   Синхронизация БД с файловой системой\
-   Docker + Nginx + Gunicorn + Postgres

## Запуск

    cp env.example .env
    docker-compose up -d --build

## API

-   GET /api/albums\
-   GET /api/articles/`<album>`{=html}\
-   POST /upload\
-   POST /api/export-xlsx\
-   POST /api/export-csv\
-   GET /api/sync\
-   DELETE /api/delete-album/`<album>`{=html}

## Архитектура

-   Flask + Gunicorn\
-   Nginx reverse‑proxy\
-   Postgres\
-   Keycloak OAuth\
-   ZIP‑процессор\
-   SyncManager\
-   DocumentGenerator
