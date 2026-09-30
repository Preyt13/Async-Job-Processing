FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

RUN chmod +x ./scripts/*.sh

# Bind host/port come from env (API_HOST, PORT/API_PORT). See scripts/run_api.sh.
CMD ["./scripts/run_api.sh"]
