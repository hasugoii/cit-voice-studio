ARG APP_IMAGE=cit-voice-studio:selfhost-vps
FROM ${APP_IMAGE}
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/hasugoii/cit-voice-studio" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="CIT Voice Studio selfhost gateway"
USER root
RUN apt-get update && apt-get install -y --no-install-recommends nginx clang g++ make && rm -rf /var/lib/apt/lists/*
# Optional phonemizers reuse the installer's managed Python at this fixed path.
RUN ln -s /data/gpu_venv /app/gpu_venv
COPY nginx.conf /etc/nginx/nginx.conf.template
COPY start.sh /usr/local/bin/start-cit
RUN chmod 755 /usr/local/bin/start-cit
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start-cit"]
