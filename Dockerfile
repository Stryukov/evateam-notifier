# Бот-напоминалка EvaTeam. Один процесс: long polling + планировщик.
# Портов не открывает — входящих соединений нет.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Недостающие звенья цепочки сертификатов.
#
# Сервер EvaTeam отдаёт только свой сертификат, без промежуточного
# (GlobalSign RSA OV SSL CA 2018). Windows такое прощает — он докачивает недостающее
# звено по AIA; OpenSSL в Linux этого не делает и падает с
# «unable to verify the first certificate». Поэтому промежуточный кладём сами.
#
# Положите нужные .crt в certs/ (не коммитятся, см. .gitignore).
# Каталог копируется целиком, поэтому сборка не падает, когда он пуст.
COPY certs/ /usr/local/share/ca-certificates/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Зависимости отдельным слоем: правка кода не пересобирает их.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY evateam_bot/ ./evateam_bot/

# Не от root. data/ создаём заранее — том монтируется поверх, но при запуске
# без тома каталог всё равно должен быть доступен на запись.
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

CMD ["python", "-m", "evateam_bot.main"]
