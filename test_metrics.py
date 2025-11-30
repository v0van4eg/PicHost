#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы метрик Prometheus
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

# Устанавливаем минимальные переменные окружения для запуска
os.environ['OAUTH_CLIENT_ID'] = 'test'
os.environ['OAUTH_CLIENT_SECRET'] = 'test'
os.environ['OAUTH_REDIRECT_URI'] = 'http://localhost:5000/callback'
os.environ['OAUTH_DISCOVERY_URL'] = 'https://accounts.google.com/.well-known/openid-configuration'
os.environ['FLASK_SECRET_KEY'] = 'test'

# Имитируем работу с базой данных
sys.modules['database'] = MagicMock()
mock_db_manager = MagicMock()
mock_db_manager.execute_query.return_value = [{'total_albums': 10}]
sys.modules['database'].db_manager = mock_db_manager

# Имитируем остальные модули
sys.modules['auth_system'] = MagicMock()
sys.modules['document_generator'] = MagicMock()
sys.modules['sync_manager'] = MagicMock()
sys.modules['utils'] = MagicMock()
sys.modules['zip_processor'] = MagicMock()

# Теперь можно импортировать app
from source.app import app, update_metrics, prometheus_metrics

def test_metrics():
    print("Тестирование метрик Prometheus...")
    
    # Проверяем, что endpoint для метрик существует
    metric_endpoint = None
    for rule in app.url_map.iter_rules():
        if rule.rule == '/metrics':
            metric_endpoint = rule
            break
    
    if metric_endpoint:
        print("✓ Endpoint /metrics найден")
        print(f"  - Функция: {metric_endpoint.endpoint}")
        print(f"  - Методы: {list(metric_endpoint.methods)}")
    else:
        print("✗ Endpoint /metrics не найден")
        return False
    
    # Проверяем функцию обновления метрик
    try:
        update_metrics()
        print("✓ Функция update_metrics выполнена успешно")
    except Exception as e:
        print(f"✗ Ошибка в update_metrics: {e}")
        return False
    
    # Проверяем, что функция prometheus_metrics существует
    if prometheus_metrics:
        print("✓ Функция prometheus_metrics существует")
    else:
        print("✗ Функция prometheus_metrics не найдена")
        return False
    
    print("✓ Все тесты пройдены успешно!")
    return True

if __name__ == "__main__":
    test_metrics()