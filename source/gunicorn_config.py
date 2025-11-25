# gunicorn_config.py
bind = "0.0.0.0:5000"
workers = 2  # Уменьшено для избежания конфликтов с БД
worker_class = "sync"
timeout = 300  # Увеличено для долгих операций
keepalive = 2
max_requests = 1000  # Увеличено для стабильности
max_requests_jitter = 50
preload_app = True
