FROM python:3.12-slim

# chrony para sincronizacion de reloj (CAPA 2.3) -- corre como demonio junto al motor
RUN apt-get update && apt-get install -y --no-install-recommends chrony && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# PM2-equivalente en Docker: usar restart_policy en docker-compose.yml (CAPA 5.1)
CMD service chrony start && python main.py
