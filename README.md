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

## Настройка Keycloak

Для корректной работы с ролями в Keycloak необходимо:

1. Создать клиент OAuth2 в Keycloak
2. В настройках клиента:
   - Установить `Access Type` в `confidential`
   - В `Valid Redirect URIs` добавить URL вашего приложения: `http://ваш_домен/auth/callback`
   - В `Client Protocol` выбрать `openid-connect`
3. В разделе `Client Scopes` убедиться, что scope `roles` включен
4. В `Mappers` добавить следующие мапперы:
   - `User Realm Role Mappings` - для получения ролей realm
   - `User Client Role Mappings` - для получения ролей клиента
   - `Group Membership` - для получения групп пользователя (если используются как роли)

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
