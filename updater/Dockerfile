FROM docker:28-cli

RUN apk add --no-cache \
    python3 \
    py3-pip \
    bash \
    curl \
    tar

WORKDIR /app

COPY requirements.txt .

RUN pip install \
    --break-system-packages \
    --no-cache-dir \
    -r requirements.txt

COPY main.py .

EXPOSE 9000

CMD ["uvicorn","main:app","--host","0.0.0.0","--port","9000"]