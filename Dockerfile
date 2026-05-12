FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias (FastAPI, Uvicorn, PyJWT, Psycopg2 para Postgres)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app

# Exponer el puerto para K3s
EXPOSE 8000

# Arrancar el servidor asíncrono
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]