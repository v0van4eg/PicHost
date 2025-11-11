FROM python:slim

WORKDIR /app

COPY source/requirements.txt /app/

RUN pip install --upgrade pip && pip install -r requirements.txt

# Копируем все исходные файлы
COPY source /app/

EXPOSE 5000

CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]
