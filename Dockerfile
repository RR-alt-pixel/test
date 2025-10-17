# ==============================
# 📦 1. БАЗОВЫЙ ОБРАЗ
# ==============================
FROM python:3.11-slim

# ==============================
# ⚙️ 2. УСТАНОВКА СИСТЕМНЫХ ЗАВИСИМОСТЕЙ
# ==============================
COPY apt-packages.txt .

RUN apt-get update && \
    xargs apt-get install -y --no-install-recommends -f < apt-packages.txt && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ==============================
# 🧱 3. УСТАНОВКА PYTHON-ПАКЕТОВ
# ==============================
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ==============================
# 📂 4. КОПИРУЕМ ПРОЕКТ
# ==============================
WORKDIR /app
COPY . .

# ==============================
# 🔑 5. ДОБАВЛЯЕМ ПРАВА НА start.sh
# ==============================
RUN chmod +x start.sh

# ==============================
# 🚀 6. ЗАПУСК
# ==============================
CMD ["./start.sh"]
