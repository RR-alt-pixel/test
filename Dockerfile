# Используем официальный минимальный Python
FROM python:3.11-slim

# Устанавливаем системные пакеты для Playwright (браузеры Chromium)
COPY apt-packages.txt .
RUN apt-get update && xargs apt-get install -y < apt-packages.txt && apt-get clean

# Создаем рабочую директорию
WORKDIR /app

# Копируем все файлы проекта
COPY . .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем браузеры Playwright
RUN python -m playwright install --with-deps

# Разрешаем запуск скрипта
RUN chmod +x start.sh

# Открываем порт 8000 (Render использует этот порт)
EXPOSE 8000

# Стартуем сервер
CMD ["./start.sh"]
