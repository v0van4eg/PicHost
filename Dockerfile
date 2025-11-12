FROM python:slim

WORKDIR /app

COPY source/requirements.txt /app/

RUN pip install --upgrade pip && pip install -r requirements.txt

# Копируем все исходные файлы
COPY source /app/

# Устанавливаем переменные окружения для оптимизации Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
