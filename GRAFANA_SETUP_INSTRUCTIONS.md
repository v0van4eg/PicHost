# Установка и настройка Grafana дашборда

## Обзор

Ваше приложение уже настроено для сбора метрик в формате Prometheus и включает в себя готовый дашборд для Grafana. Ниже приведены инструкции по установке и настройке мониторинга.

## Компоненты системы мониторинга

1. **Приложение** - собирает метрики и предоставляет их по адресу `/metrics`
2. **Prometheus** - собирает метрики с приложения
3. **Grafana** - визуализирует метрики в виде дашборда
4. **Готовый дашборд** - JSON-файл для импорта в Grafana

## Файлы системы мониторинга

- `source/app.py` - реализация метрик в приложении
- `grafana_dashboard.json` - дашборд для Grafana
- `GRAFANA_DASHBOARD_README.md` - подробная документация по дашборду
- `PROMETHEUS_METRICS.md` - описание всех метрик
- `METRICS_DASHBOARD_SUMMARY.md` - краткое описание системы мониторинга

## Установка и настройка

### 1. Установка Grafana

```bash
# Используя Docker
docker run -d -p 3000:3000 --name=grafana grafana/grafana

# Или для Ubuntu/Debian
sudo apt-get install -y grafana
sudo systemctl start grafana-server
sudo systemctl enable grafana-server
```

### 2. Установка Prometheus (если еще не установлен)

```bash
# Используя Docker
docker run -d -p 9090:9090 --name prometheus -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus

# Пример prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'pichosting_app'
    static_configs:
      - targets: ['host.docker.internal:5000']  # или IP-адрес вашего приложения
```

### 3. Настройка источника данных Prometheus в Grafana

1. Откройте веб-интерфейс Grafana (по умолчанию http://localhost:3000)
2. Войдите с учетными данными по умолчанию (admin/admin)
3. Перейдите в Configuration → Data Sources
4. Нажмите "Add data source"
5. Выберите "Prometheus"
6. Укажите URL Prometheus (например, http://localhost:9090)
7. Нажмите "Save & Test"

### 4. Импорт дашборда

1. В Grafana перейдите на главную страницу
2. Нажмите "+" в левой панели и выберите "Import dashboard"
3. Выберите файл `/workspace/grafana_dashboard.json` или вставьте его содержимое в поле "Import via panel json"
4. Нажмите "Load"
5. Выберите источник данных Prometheus
6. Нажмите "Import"

## Метрики, отслеживаемые в дашборде

### Общая статистика
- `album_count` - количество альбомов
- `article_count` - количество артикулов
- `file_count` - количество файлов

### Дисковое пространство
- `disk_usage_bytes_total` - общее дисковое пространство
- `disk_usage_bytes_used` - используемое дисковое пространство
- `disk_usage_bytes_free` - свободное дисковое пространство

### Производительность
- `http_requests_total` - количество HTTP-запросов
- `http_request_duration_seconds` - время выполнения HTTP-запросов
- `active_connections` - количество активных подключений

### Состояние системы
- `database_size_bytes` - размер базы данных
- `application_uptime_seconds` - время работы приложения

## Проверка работы системы

1. Убедитесь, что приложение запущено и доступен endpoint `/metrics`
2. Проверьте, что Prometheus собирает метрики с приложения
3. Убедитесь, что Grafana может получить данные из Prometheus
4. Проверьте, что дашборд отображает актуальные данные

## Дополнительные возможности

### Настройка алертов
Вы можете настроить алерты в Grafana для следующих ситуаций:
- Заканчивается дисковое пространство
- Высокое время ответа приложения
- Большое количество ошибок HTTP

### Мониторинг производительности
Дашборд позволяет отслеживать:
- Скорость обработки запросов
- Распределение по HTTP-методам и кодам состояния
- Использование ресурсов системы

## Устранение неполадок

Если дашборд не отображает данные:
1. Проверьте, что endpoint `/metrics` возвращает данные
2. Убедитесь, что Prometheus правильно настроен для сбора метрик
3. Проверьте, что источник данных в Grafana настроен корректно
4. Убедитесь, что приложение запущено и функционирует нормально