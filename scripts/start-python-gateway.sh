#!/usr/bin/env bash
export PORT=18790
cd ./
echo "Starting Python gateway on port $PORT at $(date)"
exec /usr/bin/python3 -u ./gateway.py 2>&1
