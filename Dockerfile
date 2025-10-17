# ---------- БАЗА ----------
FROM python:3.11-slim

# ---------- УСТАНОВКА СИСТЕМНЫХ ПАКЕТОВ ----------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl wget gnupg ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libgtk-3-0 libnss3 libxshmfence1 libx11-xcb1 \
    libxext6 libx11-6 libpangocairo-1.0-0 libpango-1.0-0 \
    fonts-noto-color-emoji fonts-unifont && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------- РАБОЧАЯ ПАПКА ----------
WORKDIR /app
COPY . .

# ---------- УСТАНОВКА PYTHON-ПАКЕТОВ ----------
RUN pip install --no-cache-dir -r requirements.txt

# ---------- УСТАНОВКА БРАУЗЕРА PLAYWRIGHT ----------
RUN python -m playwright install chromium

# ---------- СТАРТ ----------
CMD ["bash", "start.sh"]
