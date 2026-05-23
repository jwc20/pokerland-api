#!/usr/bin/env sh
set -eu

# Starts a local PostgreSQL container matching Django DATABASES settings.
CONTAINER_NAME="pokerland-postgres"
IMAGE="postgres:16-alpine"
DB_NAME="postgres"
DB_USER="postgres"
DB_PASSWORD='Example1!'
HOST_PORT="5434"
CONTAINER_PORT="5432"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Removing existing container: ${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null
fi

docker run -d \
  --name "${CONTAINER_NAME}" \
  -e POSTGRES_DB="${DB_NAME}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  "${IMAGE}" >/dev/null

echo "PostgreSQL started in Docker"
echo "Container: ${CONTAINER_NAME}"
echo "Connection: postgresql://${DB_USER}:${DB_PASSWORD}@localhost:${HOST_PORT}/${DB_NAME}"
