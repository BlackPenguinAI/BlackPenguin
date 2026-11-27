ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
ARG APP_ROOT
COPY continuous_overlay.py /tmp/continuous_overlay.py
RUN python /tmp/continuous_overlay.py "$APP_ROOT" && rm /tmp/continuous_overlay.py
USER 10001:10001
