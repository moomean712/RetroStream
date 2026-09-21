#!/bin/sh
exec sh "$(dirname "$0")/docker/update-docker.sh" "$@"
