# Мониторинг приложения с использованием Prometheus

## Обзор

Ваше приложение теперь собирает и предоставляет метрики в формате Prometheus. Эти метрики позволяют отслеживать состояние приложения, производительность и использование ресурсов.

## Доступные метрики

### Счетчики (Counters)
- `http_requests_total` - Общее количество HTTP-запросов
  - Теги: `method`, `endpoint`, `status`

### Гистограммы (Histograms)
- `http_request_duration_seconds` - Время выполнения HTTP-запросов в секундах
  - Теги: `method`, `endpoint`

### Гейджи (Gauges)
- `active_connections` - Количество активных подключений
- `album_count` - Количество альбомов
- `article_count` - Количество артикулов
- `file_count` - Количество файлов
- `disk_usage_bytes_total` - Общее дисковое пространство
  - Тег: `path`
- `disk_usage_bytes_free` - Свободное дисковое пространство
  - Тег: `path`
- `disk_usage_bytes_used` - Используемое дисковое пространство
  - Тег: `path`
- `database_size_bytes` - Размер базы данных в байтах
- `application_uptime_seconds` - Время работы приложения в секундах

## Endpoint для метрик

Метрики доступны по следующему URL:
```
/metrics
```

## Использование с Prometheus

Для сбора метрик с помощью Prometheus, добавьте в конфигурацию Prometheus следующий job:

```yaml
scrape_configs:
  - job_name: 'pichosting_app'
    static_configs:
      - targets: ['your-app-host:5000']
    scrape_interval: 30s
    scrape_timeout: 10s
```

## Примеры запросов

Ниже приведены примеры полезных запросов к Prometheus для анализа состояния приложения:

### Общее количество файлов
```
file_count
```

### Количество альбомов
```
album_count
```

### Количество артикулов
```
article_count
```

### Использование дискового пространства
```
disk_usage_bytes_used / 1024 / 1024 / 1024  # в ГБ
```

### Свободное дисковое пространство
```
disk_usage_bytes_free / 1024 / 1024 / 1024  # в ГБ
```

### Время работы приложения
```
application_uptime_seconds / 60 / 60  # в часах
```

### Среднее время ответа
```
rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])
```

### Количество запросов в секунду (RPS)
```
sum(rate(http_requests_total[5m])) by (endpoint)
```

## Права доступа

Доступ к endpoint `/metrics` не требует аутентификации, так как Prometheus обычно разворачивается в доверенной внутренней сети. Если ваша инфраструктура требует аутентификации, можно добавить соответствующий декоратор.

## Мониторинг производительности

- `http_request_duration_seconds` позволяет отслеживать время ответа на запросы
- `http_requests_total` позволяет отслеживать количество запросов и коды состояния
- Сопоставление метрик с дисковым пространством позволяет отслеживать рост объема данных

## Алерты

Примеры правил алертов для Alertmanager:

```yaml
groups:
- name: pichosting_alerts
  rules:
  - alert: HighRequestLatency
    expr: rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m]) > 1
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Высокая задержка HTTP-запросов"
      description: "Среднее время ответа превышает 1 секунду за последние 5 минут"

  - alert: DiskSpaceLow
    expr: (disk_usage_bytes_used / disk_usage_bytes_total) * 100 > 85
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Мало свободного места на диске"
      description: "Использование диска превышает 85%"
```