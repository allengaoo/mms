#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/.runtime"
MEMORIA_VERSION="${MEMORIA_VERSION:-v0.4.0}"
SAFE_VERSION="${MEMORIA_VERSION//\//-}"
SOURCE_DIR="${RUNTIME_DIR}/Memoria-${SAFE_VERSION}"
ARCHIVE="${RUNTIME_DIR}/Memoria-${SAFE_VERSION}.tar.gz"

mkdir -p "${RUNTIME_DIR}"

if [[ ! -f "${SOURCE_DIR}/docker-compose.yml" ]]; then
  mkdir -p "${SOURCE_DIR}"
  curl --fail --location --retry 3 \
    "https://codeload.github.com/matrixorigin/Memoria/tar.gz/${MEMORIA_VERSION}" \
    --output "${ARCHIVE}"
  tar -xzf "${ARCHIVE}" --strip-components=1 -C "${SOURCE_DIR}"
fi

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  master_key=""
  while IFS='=' read -r key value; do
    if [[ "${key}" == "MEMORIA_MASTER_KEY" ]]; then
      master_key="${value}"
      break
    fi
  done < "${SCRIPT_DIR}/.env"
  master_key="${master_key:-$(openssl rand -hex 32)}"
else
  master_key="$(openssl rand -hex 32)"
fi
cat > "${SCRIPT_DIR}/.env" <<EOF
MEMORIA_MASTER_KEY=${master_key}
DOCKER_UID=$(id -u)
DOCKER_GID=$(id -g)
MEMORIA_SOURCE_DIR=${SOURCE_DIR}
MATRIXONE_IMAGE=matrixorigin/matrixone:3.0.17
POC_DATA_DIR=./data-v0.4.0
EOF

echo "Memoria runtime prepared at ${SOURCE_DIR}"
echo "Pinned version: ${MEMORIA_VERSION}"
