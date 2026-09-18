#!/usr/bin/env bash
# Starts the RocketMQ broker with a brokerIP1 that callers can actually reach.
#
# The image cannot substitute environment variables inside a mounted config file,
# so the value is appended to a copy of the base config at start-up.
#
#   BROKER_IP1=127.0.0.1      (default) host-run services and tests
#   BROKER_IP1=rocketmq-broker          services running inside the compose network
#
# Without this, the broker advertises its container-internal IP and every client
# outside the compose network fails to connect (docs/compatibility-report.md 5.11).
set -euo pipefail

BROKER_IP1="${BROKER_IP1:-127.0.0.1}"
NAMESRV_ADDR="${NAMESRV_ADDR:-rocketmq-namesrv:9876}"
ROCKETMQ_HOME_DIR="$(ls -d /home/rocketmq/rocketmq-* | head -1)"

cp /home/rocketmq/broker.conf.base /home/rocketmq/broker.conf
# Leading newline is required: a config file without a trailing newline would
# otherwise concatenate this onto the previous line, and the broker would silently
# fall back to advertising its container-internal IP.
printf '\nbrokerIP1 = %s\n' "${BROKER_IP1}" >> /home/rocketmq/broker.conf

echo "starting broker: brokerIP1=${BROKER_IP1} namesrv=${NAMESRV_ADDR}"
exec "${ROCKETMQ_HOME_DIR}/bin/mqbroker" -c /home/rocketmq/broker.conf -n "${NAMESRV_ADDR}"