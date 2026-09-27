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
# Dev-only junk in version.py (e.g. "2.0.0 (wip)") breaks setuptools in the image;
# keep SemVer pre-releases (-alpha.N / -rc.N). Host file stays unchanged.
RUN python -c "from version import rewrite_version_file_for_image; rewrite_version_file_for_image()"
RUN pip install --no-cache-dir -r requirements.txt

# Explicit copies only (S6470) — avoid recursive COPY . . pulling secrets/junk.
COPY docker/ docker/
COPY house_config/ house_config/
COPY settings/ settings/
COPY ehal/ ehal/
# Full share/ tree (ehal schemas, loxone templates, hardware_profiles, registry) —
# not only share/config/. Omitting share/ehal breaks live EHAL JSON Schema validation.
COPY share/ share/
COPY logger_config.py app.py main.py config.py ./
RUN mkdir -p earnie_env/runtime
COPY earnie_env/runtime/local_settings.example.json earnie_env/runtime/
COPY .env.example ./

# Empty BUILD_DATE skips the clock preflight (ad-hoc local builds).
# scripts/build_container.py always passes a UTC ISO-8601 stamp.
ARG BUILD_DATE=
RUN printf '%s' "$BUILD_DATE" > docker/BUILD_DATE \
    && sed -i 's/\r$//' docker/entrypoint.sh docker/preflight.sh docker/healthcheck.sh \
    && chmod +x docker/entrypoint.sh docker/healthcheck.sh

# Templates + public tariffs catalog live in share/config/ (git). Supplement runtime/.env examples.
RUN mkdir -p share/config \
    && cp earnie_env/runtime/local_settings.example.json share/config/local_settings.example.json \
    && cp .env.example share/config/.env.example

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD /bin/sh docker/healthcheck.sh

ENTRYPOINT ["/bin/sh", "docker/entrypoint.sh"]
CMD ["python", "-m", "scripts.run_streamlit"]
