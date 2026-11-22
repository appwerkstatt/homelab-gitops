# Vorlage für /opt/n8n-sandbox/.env auf der VM (Compose liest sie für Interpolation UND env_file). Auf dem Mac rendern (op CLI) und per scp kopieren:
#   op inject -i vms/n8n-sandbox/sandbox.env.tpl -o /tmp/n8n-sandbox.env
#   scp /tmp/n8n-sandbox.env n8n-sandbox:/opt/n8n-sandbox/.env && rm /tmp/n8n-sandbox.env
# Auf der VM: chmod 600 /opt/n8n-sandbox/.env. Gerenderte Datei NIE committen.

# Release-Version (api, runner, sandbox gemeinsam). Releases: ghcr.io/n8n-io/n8n-sandbox-service-api
N8N_SANDBOX_VERSION=1.16.0

# API-Key(s), mit denen n8n die API aufruft. Gleicher Wert wie N8N_SANDBOX_SERVICE_API_KEY im n8n-Stack.
SANDBOX_API_KEYS={{ op://AppsFab/homelab-n8n-sandbox/api-key }}
# Registrierung Runner -> API: beide Seiten derselbe Wert.
SANDBOX_API_RUNNER_REGISTRATION_TOKEN={{ op://AppsFab/homelab-n8n-sandbox/runner-registration-token }}
SANDBOX_RUNNER_REGISTRATION_TOKEN={{ op://AppsFab/homelab-n8n-sandbox/runner-registration-token }}
# Key, mit dem die API den Runner anspricht: beide Seiten derselbe Wert.
SANDBOX_API_RUNNER_API_KEY={{ op://AppsFab/homelab-n8n-sandbox/runner-api-key }}
SANDBOX_RUNNER_API_KEYS={{ op://AppsFab/homelab-n8n-sandbox/runner-api-key }}
