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

RUN chmod +x /app/scripts/migrate.py

EXPOSE 5000

ENTRYPOINT ["/app/scripts/vpn-up.sh"]
CMD ["python", "app.py"]
