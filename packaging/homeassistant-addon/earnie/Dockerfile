# Earnie Home-Assistant-Add-on — dünner Wrapper um das bestehende Release-Image
# (Architektur-Entscheidung "Image-Wrapper" statt Git-Clone-Build, siehe
# Entwicklungsplan-Doku). Die App selbst (Dockerfile/Entrypoint) bleibt die
# einzige Quelle der Wahrheit in docker/Dockerfile im Hauptrepo.
ARG EARNIE_VERSION=2.4.0
FROM ghcr.io/jochentcc/earnie-energy:${EARNIE_VERSION}

# run.sh liest /data/options.json (Supervisor) selbst — kein HA-Base-Image
# hier, daher kein bashio; jq übernimmt das Parsen (siehe Entwicklungsplan-Doku).
RUN apt-get update && apt-get install -y --no-install-recommends jq \
    && rm -rf /var/lib/apt/lists/*

COPY run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh && chmod a+x /run.sh

# init: false in config.yaml -> Supervisor überlässt PID-1-Handling diesem
# ENTRYPOINT (kein s6-overlay in 0.1).
ENTRYPOINT [ "/run.sh" ]
