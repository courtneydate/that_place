FROM eclipse-mosquitto:2

# Install openssl so the entrypoint can generate self-signed dev certificates.
# The base image is Alpine-based; openssl is not included by default.
USER root
RUN apk add --no-cache openssl
