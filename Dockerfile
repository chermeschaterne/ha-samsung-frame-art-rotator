ARG BUILD_FROM=ghcr.io/hassio-addons/base:15.0.7
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# Ensure pip is available (base image may or may not have it)
RUN if ! command -v pip3 >/dev/null 2>&1; then \
        apk add --no-cache python3 py3-pip; \
    fi

WORKDIR /app

# Install Python dependencies (Pillow + samsungtvws + apscheduler + quart + hypercorn)
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY app/ /app/app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Labels
LABEL \
    io.hass.name="Samsung Frame Art Rotator" \
    io.hass.description="Daily rotation of Immich album images on Samsung Frame TV" \
    io.hass.arch="aarch64|amd64|armv7|armhf|i386" \
    io.hass.type="addon" \
    io.hass.version="1.0.0" \
    maintainer="Christoph Materne <chermes.chaterne@gmail.com>"

CMD [ "/run.sh" ]
