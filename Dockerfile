FROM python:3.11-slim

WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы бота
COPY bot.py .
COPY bot_sessions.db .

# Запускаем бота
CMD ["python", "-u", "bot.py"]
