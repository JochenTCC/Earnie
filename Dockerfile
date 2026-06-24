# Das '--platform' sorgt dafür, dass das Image immer passend für dein NAS gebaut wird
FROM --platform=linux/amd64 python:3.14-slim

RUN apt-get update && apt-get install -y \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml version.py README.md requirements.txt ./
COPY optimizer/ optimizer/
COPY data/ data/
COPY integrations/ integrations/
COPY runtime_store/ runtime_store/
COPY ui/ ui/
COPY simulation/ simulation/
COPY scripts/ scripts/
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

ENTRYPOINT ["/bin/sh", "docker-entrypoint.sh"]
CMD ["python", "main.py"]
