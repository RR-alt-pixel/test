# Используем базовый образ Python с необходимыми системными пакетами
FROM python:3.11-slim

# Установка системных зависимостей для Playwright (Chromium)
# ... (Предыдущие строки) ...

# Установка системных зависимостей для Playwright (Chromium)
RUN apt-get update && apt-get install -y \
    chromium \
    libnss3 \
    libfontconfig \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
    
# ... (Последующие строки) ...

# Установка рабочего каталога
WORKDIR /app

# Копирование файла требований и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка Playwright (скачивание драйверов)
RUN playwright install chromium

# Копирование основного кода приложения
COPY app.py .

# Определение порта (Render требует 10000 по умолчанию)
ENV PORT=10000

# Команда для запуска Gunicorn
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:10000"]
