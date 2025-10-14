# Используем базовый образ Python с необходимыми системными пакетами
FROM python:3.11-slim

# Установка системных зависимостей для Playwright (Chromium)
# Это ключевой шаг, без которого Playwright не сможет запустить браузер
RUN apt-get update && apt-get install -y \
    chromium \
    # Дополнительные зависимости для Playwright
    libnss3 \
    libfontconfig \
    libgconf-2-4 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Установка рабочего каталога
WORKDIR /app

# Копирование файла требований и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка Playwright (скачивание драйверов)
RUN playwright install chromium

# Копирование основного кода приложения
COPY app.py .

# Определение порта
ENV PORT=10000

# Команда для запуска Gunicorn
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:10000"]
