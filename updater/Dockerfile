FROM python:3.13-slim

WORKDIR /app

# Grundlegende Pakete
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        unzip \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
        $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Docker Compose Plugin
RUN mkdir -p /usr/libexec/docker/cli-plugins \
    && curl -SL \
        https://github.com/docker/compose/releases/download/v2.39.2/docker-compose-linux-x86_64 \
        -o /usr/libexec/docker/cli-plugins/docker-compose \
    && chmod +x /usr/libexec/docker/cli-plugins/docker-compose

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY updater.py .

CMD ["uvicorn", "updater:app", "--host", "0.0.0.0", "--port", "9000"]