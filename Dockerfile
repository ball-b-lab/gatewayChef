FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# WireGuard into the gateway VPN (scripts/vpn-up.sh), ping for the VPN check
RUN apt-get update && apt-get install -y --no-install-recommends wireguard-tools iproute2 iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# build stamp for the page header (Coolify passes SOURCE_COMMIT as build arg)
ARG SOURCE_COMMIT=""
RUN echo "${SOURCE_COMMIT}" > /app/.build_commit && date -u +%Y-%m-%dT%H:%M:%SZ > /app/.build_time

RUN chmod +x /app/scripts/migrate.py

EXPOSE 5000

ENTRYPOINT ["/app/scripts/vpn-up.sh"]
CMD ["python", "app.py"]
