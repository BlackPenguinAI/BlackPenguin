FROM python:3.12-slim

ARG APP_COMMIT_SHA=unknown

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app
COPY ./alembic.ini /app/alembic.ini
COPY ./alembic /app/alembic
COPY ./migrations /app/migrations

ENV APP_COMMIT_SHA=$APP_COMMIT_SHA
ENV FORWARDED_ALLOW_IPS="127.0.0.1,172.17.0.1"

LABEL org.opencontainers.image.revision=$APP_COMMIT_SHA

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]

