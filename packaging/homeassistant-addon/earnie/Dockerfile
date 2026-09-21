# Earnie Home-Assistant-Add-on — dünner Wrapper um das bestehende Release-Image
# (Architektur-Entscheidung "Image-Wrapper" statt Git-Clone-Build, siehe
# Entwicklungsplan-Doku). Die App selbst (Dockerfile/Entrypoint) bleibt die
# einzige Quelle der Wahrheit in docker/Dockerfile im Hauptrepo.
ARG EARNIE_VERSION=2.5.3-alpha.6
FROM ghcr.io/jochentcc/earnie-energy:${EARNIE_VERSION}

# run.sh liest /data/options.json (Supervisor) selbst — kein HA-Base-Image
# hier, daher kein bashio; jq übernimmt das Parsen. nginx terminiert Ingress
# und re-attached den Ingress-Pfad vor Streamlit (siehe nginx/ + run.sh).
RUN apt-get update && apt-get install -y --no-install-recommends jq nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

COPY nginx/ingress.conf.template /etc/earnie-addon/nginx/ingress.conf.template
COPY run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh && chmod a+x /run.sh

# init: false in config.yaml -> Supervisor überlässt PID-1-Handling diesem
# ENTRYPOINT (kein s6-overlay in 0.1).
ENTRYPOINT [ "/run.sh" ]
