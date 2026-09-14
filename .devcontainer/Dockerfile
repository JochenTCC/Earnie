# Dev image aligned with docker/Dockerfile (python:3.14-slim).
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Vienna
ENV PYTHONUTF8=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore

WORKDIR /workspaces
