#!/usr/bin/env bash
echo "🚀 Проверка браузера Playwright..."
python -m playwright install chromium || echo "⚠️ Chromium уже установлен или не требуется"

echo "🚀 Запуск Gunicorn..."
exec gunicorn app:app --workers 1 --bind 0.0.0.0:8000
