FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias (FastAPI, Uvicorn, PyJWT, Psycopg2, Motor, etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos todo el código fuente modular
COPY ./app /app/app

# Exponer el puerto para K3s y Docker Compose local
EXPOSE 8000

# Arrancar el servidor asíncrono apuntando a tu nuevo entrypoint
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]