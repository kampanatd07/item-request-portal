FROM python:3.12-slim

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# One worker: the mail limiter spaces sends per process, and Exchange allows
# about 30 a minute per mailbox (STORY-006 AC 7). --no-proxy-headers: the app
# reads X-Forwarded-For itself, from FORWARDED_ALLOW_IPS only (app/main.py).
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-proxy-headers"]
