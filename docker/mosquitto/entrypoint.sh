#!/bin/sh
# Mosquitto entrypoint — bootstraps certificates and Dynamic Security on first start.
#
# Certificate setup (two modes):
#   Production: set MQTT_CA_CERT_B64, MQTT_CA_KEY_B64, MQTT_BROKER_CERT_B64,
#               MQTT_BROKER_KEY_B64 as base64-encoded PEM env vars. The script
#               writes them to /mosquitto/certs/ on every start.
#   Dev:        Leave those vars unset. The script auto-generates a self-signed
#               CA and broker cert on first start and stores them in the certs
#               volume. The base64 values are printed to stdout so they can be
#               copied into .env.
#
# Dynamic Security bootstrap:
#   On first start (no dynamic-security.json), initialises the plugin config
#   with the admin account from MQTT_ADMIN_USERNAME / MQTT_ADMIN_PASSWORD.
set -e

CERTS_DIR=/mosquitto/certs
CONFIG=/mosquitto/config/dynamic-security.json

mkdir -p "$CERTS_DIR"

# ---------------------------------------------------------------------------
# CA certificate
# ---------------------------------------------------------------------------
if [ -n "$MQTT_CA_CERT_B64" ] && [ -n "$MQTT_CA_KEY_B64" ]; then
    printf '%s' "$MQTT_CA_CERT_B64" | base64 -d > "$CERTS_DIR/ca.crt"
    printf '%s' "$MQTT_CA_KEY_B64"  | base64 -d > "$CERTS_DIR/ca.key"
    chmod 400 "$CERTS_DIR/ca.key"
    echo "[mqtt] CA certificate loaded from environment."
elif [ ! -f "$CERTS_DIR/ca.key" ]; then
    echo "[mqtt] Generating self-signed CA (dev mode)..."
    openssl genrsa -out "$CERTS_DIR/ca.key" 2048 2>/dev/null
    openssl req -new -x509 -days 3650 \
        -key  "$CERTS_DIR/ca.key" \
        -out  "$CERTS_DIR/ca.crt" \
        -subj "/CN=That Place MQTT CA/O=That Place" 2>/dev/null
    chmod 400 "$CERTS_DIR/ca.key"
    echo "[mqtt] CA certificate generated. Add to .env:"
    echo "MQTT_CA_CERT_B64=$(base64 < $CERTS_DIR/ca.crt | tr -d '\n')"
    echo "MQTT_CA_KEY_B64=$(base64 < $CERTS_DIR/ca.key | tr -d '\n')"
else
    echo "[mqtt] CA certificate found in volume."
fi

# ---------------------------------------------------------------------------
# Broker certificate (signed by the CA)
# ---------------------------------------------------------------------------
if [ -n "$MQTT_BROKER_CERT_B64" ] && [ -n "$MQTT_BROKER_KEY_B64" ]; then
    printf '%s' "$MQTT_BROKER_CERT_B64" | base64 -d > "$CERTS_DIR/broker.crt"
    printf '%s' "$MQTT_BROKER_KEY_B64"  | base64 -d > "$CERTS_DIR/broker.key"
    chmod 400 "$CERTS_DIR/broker.key"
    echo "[mqtt] Broker certificate loaded from environment."
elif [ ! -f "$CERTS_DIR/broker.key" ]; then
    echo "[mqtt] Generating broker certificate (dev mode)..."
    openssl genrsa -out "$CERTS_DIR/broker.key" 2048 2>/dev/null
    openssl req -new \
        -key "$CERTS_DIR/broker.key" \
        -out "$CERTS_DIR/broker.csr" \
        -subj "/CN=mosquitto/O=That Place" 2>/dev/null
    openssl x509 -req -days 730 \
        -in      "$CERTS_DIR/broker.csr" \
        -CA      "$CERTS_DIR/ca.crt" \
        -CAkey   "$CERTS_DIR/ca.key" \
        -CAcreateserial \
        -out     "$CERTS_DIR/broker.crt" 2>/dev/null
    rm -f "$CERTS_DIR/broker.csr"
    chmod 400 "$CERTS_DIR/broker.key"
    echo "[mqtt] Broker certificate generated."
else
    echo "[mqtt] Broker certificate found in volume."
fi

# Ensure cert files are readable by the mosquitto process user
chown -R mosquitto:mosquitto "$CERTS_DIR" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Dynamic Security bootstrap
# ---------------------------------------------------------------------------
if [ ! -f "$CONFIG" ]; then
    : "${MQTT_ADMIN_USERNAME:?MQTT_ADMIN_USERNAME must be set}"
    : "${MQTT_ADMIN_PASSWORD:?MQTT_ADMIN_PASSWORD must be set}"
    echo "[mqtt] Initialising Dynamic Security..."
    mosquitto_ctrl dynsec init "$CONFIG" \
        "$MQTT_ADMIN_USERNAME" "$MQTT_ADMIN_PASSWORD"
    echo "[mqtt] Dynamic Security initialised. Admin: $MQTT_ADMIN_USERNAME"
fi

exec /docker-entrypoint.sh /usr/sbin/mosquitto \
    -c /mosquitto/config/mosquitto.conf "$@"
