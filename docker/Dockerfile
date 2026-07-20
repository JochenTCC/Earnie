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

# Templates + public tariffs catalog live in share/config/ (git). Supplement runtime/.env examples.
RUN mkdir -p share/config \
    && cp earnie_env/runtime/local_settings.example.json share/config/local_settings.example.json \
    && cp .env.example share/config/.env.example

ENTRYPOINT ["/bin/sh", "docker/entrypoint.sh"]
CMD ["python", "-m", "scripts.run_streamlit"]
