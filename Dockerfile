# Das '--platform' sorgt dafür, dass das Image immer passend für dein NAS gebaut wird
FROM --platform=linux/amd64 python:3.14-slim

RUN apt-get update && apt-get install -y \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
