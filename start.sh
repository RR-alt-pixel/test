#!/usr/bin/env bash
echo "🚀 Установка браузеров Playwright..."
python -m playwright install --with-deps

echo "🚀 Запуск Gunicorn..."
exec gunicorn app:app --workers 1 --bind 0.0.0.0:8000
