FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias (FastAPI, Uvicorn, PyJWT, Psycopg2, Motor, etc.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos todo el código fuente modular
COPY ./app /app/app

# Exponer el puerto para K3s y Docker Compose local
EXPOSE 8000

# Confiar únicamente en los proxies conocidos. En producción, sobrescribir esta
# variable si la red del proxy usa otra IP o subred.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,172.17.0.1"

# Procesar X-Forwarded-Proto para que FastAPI genere URLs HTTPS cuando el TLS
# termina en el proxy inverso.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
