#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:?target node required}"
SELF="rabbit@$(hostname)"

echo "[join] self=${SELF} target=rabbit@${TARGET}"

echo "[join] waiting for local node..."
until rabbitmq-diagnostics -q ping; do
  sleep 1
done

echo "[join] waiting for target node rabbit@${TARGET}..."
for i in $(seq 1 90); do
  if rabbitmq-diagnostics -n "rabbit@${TARGET}" -q ping >/dev/null 2>&1; then
    echo "[join] target is reachable"
    break
  fi
  sleep 1
  if [ "$i" -eq 90 ]; then
    echo "[join] ERROR: target not reachable after 90s"
    exit 69
  fi
done

echo "[join] stopping app..."
rabbitmqctl stop_app

echo "[join] resetting node..."
rabbitmqctl reset

echo "[join] joining cluster..."
rabbitmqctl join_cluster "rabbit@${TARGET}"

echo "[join] starting app..."
rabbitmqctl start_app

rabbitmqctl cluster_status
