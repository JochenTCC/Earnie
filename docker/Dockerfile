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
# Dev-only suffixes in version.py (e.g. "2.0.0 (wip)") break setuptools in the image;
# normalize inside the build layer — host version.py stays unchanged.
RUN python -c "import re; from pathlib import Path; p=Path('version.py'); t=p.read_text(); m=re.search(r'__version__\s*=\s*[\"\\']([^\"\\']+)[\"\\']', t); raw=(m.group(1) if m else '0.0.0'); semver=re.match(r'(\d+(?:\.\d+)*)', raw); p.write_text('__version__ = \"' + (semver.group(1) if semver else '0.0.0') + '\"\\n')"
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh

RUN mkdir -p share/config \
    && cp earnie_env/config/config.example.json share/config/config.example.json \
    && cp earnie_env/config/config.minimal.json share/config/config.minimal.json \
    && cp earnie_env/config/config.schema.json share/config/config.schema.json \
    && cp earnie_env/config/backtesting_scenarios.example.json share/config/backtesting_scenarios.example.json \
    && cp earnie_env/config/backtesting_scenarios.minimal.json share/config/backtesting_scenarios.minimal.json \
    && cp earnie_env/config/backtesting_scenarios.schema.json share/config/backtesting_scenarios.schema.json \
    && cp earnie_env/config/tariffs.example.json share/config/tariffs.example.json \
    && cp earnie_env/config/tariffs.minimal.json share/config/tariffs.minimal.json \
    && cp earnie_env/config/tariffs.schema.json share/config/tariffs.schema.json \
    && cp earnie_env/config/house_profiles.example.json share/config/house_profiles.example.json \
    && cp earnie_env/config/house_profiles.minimal.json share/config/house_profiles.minimal.json \
    && cp earnie_env/config/house_profiles.schema.json share/config/house_profiles.schema.json \
    && cp earnie_env/config/components.example.json share/config/components.example.json \
    && cp earnie_env/config/components.minimal.json share/config/components.minimal.json \
    && cp earnie_env/config/components.schema.json share/config/components.schema.json \
    && cp earnie_env/config/deviation_rules.example.json share/config/deviation_rules.example.json \
    && cp earnie_env/config/deviation_rules.schema.json share/config/deviation_rules.schema.json \
    && cp earnie_env/runtime/local_settings.example.json share/config/local_settings.example.json \
    && cp .env.example share/config/.env.example

ENTRYPOINT ["/bin/sh", "docker/entrypoint.sh"]
CMD ["python", "-m", "scripts.run_streamlit"]
