# === ОФИЦИАЛЬНЫЙ ОБРАЗ PYTHON ===
FROM python:3.11-slim

# === СИСТЕМНЫЕ ПАКЕТЫ ДЛЯ PLAYWRIGHT (браузеры Chromium) ===
COPY apt-packages.txt .
RUN apt-get update && xargs apt-get install -y < apt-packages.txt && apt-get clean

# === РАБОЧАЯ ДИРЕКТОРИЯ ===
WORKDIR /app

# === КОПИРУЕМ ПРОЕКТ ===
COPY . .

# === УСТАНАВЛИВАЕМ PYTHON-ЗАВИСИМОСТИ ===
RUN pip install --no-cache-dir -r requirements.txt

# === УСТАНАВЛИВАЕМ БРАУЗЕРЫ PLAYWRIGHT ===
RUN python -m playwright install --with-deps

# === ДЕЛАЕМ start.sh ИСПОЛНЯЕМЫМ ===
RUN chmod +x start.sh

# === ОТКРЫВАЕМ ПОРТ ===
EXPOSE 8000

# === КОМАНДА ЗАПУСКА ===
CMD ["./start.sh"]
