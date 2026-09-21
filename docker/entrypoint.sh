#!/bin/sh
set -eu

for directory in /data /cache; do
    if [ ! -d "$directory" ]; then
        echo "RetroStream: required directory $directory is missing." >&2
        exit 1
    fi
    if [ ! -w "$directory" ]; then
        echo "RetroStream: $directory is not writable by container user $(id -u):$(id -g)." >&2
        echo "Use the named volumes from compose.yaml, or correct bind-mount ownership." >&2
        exit 1
    fi
done

mkdir -p /cache/deno
echo "RetroStream: initializing and migrating the database..."
retrostream --init-db
echo "RetroStream: starting application..."
exec "$@"
