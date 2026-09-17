# Dev image aligned with docker/Dockerfile (python:3.14-slim).
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
RUN groupadd --gid "${USER_GID}" "${USERNAME}" \
    && useradd --uid "${USER_UID}" --gid "${USER_GID}" -m "${USERNAME}" \
    && chown -R "${USERNAME}:${USERNAME}" /usr/local

ENV TZ=Europe/Vienna
ENV PYTHONUTF8=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspaces

USER ${USERNAME}
