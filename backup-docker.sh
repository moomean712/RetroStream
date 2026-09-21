#!/bin/sh
exec sh "$(dirname "$0")/docker/backup-docker.sh" "$@"
