# Zielplattform beim Build setzen: --platform linux/amd64 (Synology) oder linux/arm64 (LoxBerry)
FROM python:3.14-slim

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

RUN mkdir -p share/config \
    && cp config/config.example.json share/config/config.example.json \
    && cp config/config.schema.json share/config/config.schema.json \
    && cp config/backtesting_scenarios.example.json share/config/backtesting_scenarios.example.json \
    && cp config/backtesting_scenarios.schema.json share/config/backtesting_scenarios.schema.json \
    && cp config/tariffs.example.json share/config/tariffs.example.json \
    && cp config/tariffs.schema.json share/config/tariffs.schema.json \
    && cp config/house_profiles.example.json share/config/house_profiles.example.json \
    && cp config/house_profiles.schema.json share/config/house_profiles.schema.json \
    && cp config/deviation_rules.example.json share/config/deviation_rules.example.json \
    && cp config/deviation_rules.schema.json share/config/deviation_rules.schema.json \
    && cp runtime/local_settings.example.json share/config/local_settings.example.json \
    && cp .env.example share/config/.env.example

ENTRYPOINT ["/bin/sh", "docker-entrypoint.sh"]
CMD ["python", "main.py"]
