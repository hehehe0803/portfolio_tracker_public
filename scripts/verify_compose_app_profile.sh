#!/usr/bin/env bash
set -euo pipefail

compose_file="${COMPOSE_FILE:-infra/docker-compose.yml}"

# Infra-only Compose must not require app-profile secrets.
base_services_without_secret="$(env -u SECRET_KEY docker compose -f "$compose_file" config --services | sort | tr '\n' ' ')"

# The runtime app profile intentionally requires the operator to provide a real
# SECRET_KEY in the service commands. Use an explicit throwaway value only for
# structural config checks.
export SECRET_KEY="${SECRET_KEY:-compose-check-only-not-for-runtime}"

base_services="$(docker compose -f "$compose_file" config --services | sort | tr '\n' ' ')"
app_services="$(docker compose -f "$compose_file" --profile app config --services | sort | tr '\n' ' ')"
app_config_json="$(docker compose -f "$compose_file" --profile app config --format json)"

if [[ "$base_services" != "$base_services_without_secret" ]]; then
  echo "base service set changes when SECRET_KEY is absent" >&2
  exit 1
fi

for service in timescale redis minio; do
  if [[ " $base_services " != *" $service "* ]]; then
    echo "missing base service: $service" >&2
    exit 1
  fi
done

for service in api frontend worker scheduler; do
  if [[ " $base_services " == *" $service "* ]]; then
    echo "app service is not profile-gated: $service" >&2
    exit 1
  fi
  if [[ " $app_services " != *" $service "* ]]; then
    echo "missing app profile service: $service" >&2
    exit 1
  fi
done

APP_CONFIG_JSON="$app_config_json" python - <<'PY'
import json
import os

config = json.loads(os.environ["APP_CONFIG_JSON"])
services = config["services"]
for service in ["api", "frontend", "worker", "scheduler"]:
    definition = services[service]
    if definition.get("restart") != "unless-stopped":
        raise SystemExit(f"{service} missing restart: unless-stopped")
    if "healthcheck" not in definition:
        raise SystemExit(f"{service} missing healthcheck")

for service in ["api", "worker", "scheduler"]:
    command_value = services[service].get("command", "")
    if isinstance(command_value, list):
        command = " ".join(str(part) for part in command_value)
    else:
        command = str(command_value)
    if "SECRET_KEY:?" not in command:
        raise SystemExit(f"{service} command must fail fast when SECRET_KEY is missing")

    service_env = services[service].get("environment", [])
    if isinstance(service_env, list):
        env = dict(item.split("=", 1) for item in service_env if "=" in item)
    else:
        env = service_env
    for key in ["INSTITUTION_CREDENTIALS_MASTER_KEY"]:
        if key not in env:
            raise SystemExit(f"{service} must receive {key} in runtime environment")

api_env = services["api"].get("environment", [])
if isinstance(api_env, list):
    env = dict(item.split("=", 1) for item in api_env if "=" in item)
else:
    env = api_env

for key in [
    "STARTUP_DB_INIT_ENABLED",
    "STARTUP_REPAIRS_ENABLED",
    "API_SCHEDULER_ENABLED",
]:
    if str(env.get(key, "")).lower() != "false":
        raise SystemExit(f"api app profile must default {key}=false")
PY

docker compose -f "$compose_file" --profile app config --quiet

echo "compose app profile is valid"
