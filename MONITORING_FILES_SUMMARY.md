# Сводка файлов системы мониторинга

## Обзор

В этом документе приведена сводная информация по всем файлам, связанным с системой мониторинга приложения на основе Prometheus и Grafana.

## Файлы системы мониторинга

### JSON файлы
- `grafana_dashboard.json` - готовый дашборд для импорта в Grafana

### Основные документы
- `GRAFANA_DASHBOARD_README.md` - подробная документация по дашборду
- `GRAFANA_SETUP_INSTRUCTIONS.md` - пошаговые инструкции по настройке
- `PROMETHEUS_METRICS.md` - полное описание всех метрик
- `METRICS_DASHBOARD_SUMMARY.md` - краткий обзор системы мониторинга
- `MONITORING_README.md` - главный документ по системе мониторинга
- `METRICS_README.md` - краткое руководство по метрикам

### Код приложения
- `source/app.py` - реализация метрик в коде приложения
- `test_metrics.py` - тесты для проверки метрик

## Структура дашборда Grafana

Дашборд включает в себя следующие панели:

1. **Overview** - общее количество альбомов, артикулов и файлов
2. **Disk Usage** - использование дискового пространства (гейдж)
3. **Disk Space Usage** - детальное использование дискового пространства (в байтах)
4. **Database Size** - размер базы данных
5. **Application Uptime** - время работы приложения
6. **HTTP Request Rate** - частота HTTP-запросов
7. **HTTP Status Codes** - распределение по кодам состояния
8. **HTTP Request Duration** - время выполнения запросов
9. **Active Connections** - активные подключения
10. **Entity Counts Over Time** - изменение количества сущностей со временем

## Метрики приложения

Приложение собирает следующие типы метрик:

- **Counters (счетчики)**: `http_requests_total`
- **Gauges (гейджи)**: `album_count`, `article_count`, `file_count`, `disk_usage_bytes_*`, `database_size_bytes`, `application_uptime_seconds`, `active_connections`
- **Histograms (гистограммы)**: `http_request_duration_seconds`

## Установка системы мониторинга

1. Запустите приложение с поддержкой метрик
2. Настройте Prometheus для сбора метрик с endpoint `/metrics`
3. Установите и настройте Grafana
4. Импортируйте дашборд из `grafana_dashboard.json`
5. Настройте Prometheus как источник данных в Grafana