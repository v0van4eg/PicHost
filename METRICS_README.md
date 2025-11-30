# Сбор метрик Prometheus

## Обзор

В ваше приложение добавлена возможность сбора и предоставления метрик в формате Prometheus. Это позволяет мониторить состояние приложения, производительность и использование ресурсов.

## Добавленные метрики

- `http_requests_total` - Общее количество HTTP-запросов (с тегами method, endpoint, status)
- `http_request_duration_seconds` - Время выполнения HTTP-запросов
- `album_count` - Количество альбомов
- `article_count` - Количество артикулов
- `file_count` - Количество файлов
- `disk_usage_bytes_total`, `disk_usage_bytes_free`, `disk_usage_bytes_used` - Статистика дискового пространства
- `database_size_bytes` - Размер базы данных
- `application_uptime_seconds` - Время работы приложения

## Endpoint

Метрики доступны по адресу: `http://your-app-host:5000/metrics`

## Конфигурация Prometheus

Для сбора метрик добавьте в конфигурацию Prometheus:

```yaml
scrape_configs:
  - job_name: 'pichosting_app'
    static_configs:
      - targets: ['your-app-host:5000']
    scrape_interval: 30s
```

## Требования

- Обновленный файл `requirements.txt` с добавленной зависимостью `prometheus-client`
- Приложение автоматически обновляет метрики каждые 30 секунд

Для подробной информации смотрите файл `PROMETHEUS_METRICS.md`.