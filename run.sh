#!/bin/sh
# ==============================================================================
# Samsung Frame Art Rotator - Add-on entrypoint
#
# In production (HA Supervisor):
#   - bashio is available, options are at /data/options.json
#   - we use bashio for nice colored logging
#
# In local testing (no Supervisor):
#   - bashio may not be available or may fail to contact the Supervisor API
#   - we fall back to plain logging and Python directly
# ==============================================================================
set -e

# Detect environment
if [ -d /usr/share/bashio ] || [ -f /opt/bashio/bashio ]; then
    BASHIO_AVAILABLE=1
else
    BASHIO_AVAILABLE=0
fi

# Ensure /data exists and has options
mkdir -p /data

if [ ! -f /data/options.json ] && [ -f /data/options.json.template ]; then
    cp /data/options.json.template /data/options.json
fi

if [ "$BASHIO_AVAILABLE" = "1" ]; then
    # Source bashio library (HA Supervisor provides it)
    . /opt/bashio/bashio.sh 2>/dev/null || BASHIO_AVAILABLE=0
fi

if [ "$BASHIO_AVAILABLE" = "1" ]; then
    bashio::log.info "Starting Samsung Frame Art Rotator (HA Supervisor mode)..."
    bashio::config.require 'immich.share_url' \
        || bashio::exit.nok "Missing required option: immich.share_url"
    bashio::config.require 'samsung_frame.host' \
        || bashio::exit.nok "Missing required option: samsung_frame.host"
    bashio::config.require 'samsung_frame.mac' \
        || bashio::exit.nok "Missing required option: samsung_frame.mac"
else
    echo "[$(date +%H:%M:%S)] INFO: bashio not available - running in standalone mode"
    if [ ! -f /data/options.json ]; then
        echo "[$(date +%H:%M:%S)] FATAL: /data/options.json not found"
        exit 1
    fi
fi

# Run the application
cd /app
exec python3 -m app.main
