#!/bin/sh
set -eu

DATA_DIR="${SLIK_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/config.json" ]; then
  cp /app/bot/config.example.json "$DATA_DIR/config.json"
fi

if [ ! -f "$DATA_DIR/orders.json" ]; then
  cp /app/bot/orders.example.json "$DATA_DIR/orders.json"
fi

ln -sf "$DATA_DIR/config.json" /app/bot/config.json
ln -sf "$DATA_DIR/orders.json" /app/bot/orders.json

exec "$@"
