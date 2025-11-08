FROM python:3.12-slim  # Обновил до Python 3.12 для 2025

WORKDIR /app
COPY . /app

# Установка зависимостей
RUN pip install --no-cache-dir elasticsearch sentence-transformers numpy difflib

# CMD для запуска: Сначала инспекция/загрузка, затем оценка
CMD ["sh", "-c", "python tools/load_catalog.py --index && python tools/evaluate.py"]