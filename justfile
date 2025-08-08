# CoreOS Pipeline Assistant - Justfile
# Convenient recipes for building and running the container

# Default recipe - show available commands
default:
    @just --list

# Build the container image
build:
    podman build -t coreos-pipeline-assistant .

# Force rebuild the container image (no cache)
rebuild:
    podman build --no-cache -t coreos-pipeline-assistant .

# Run container in Slack bot mode (requires full .env file)
run-slack:
    podman run --rm --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/main.py

# Run container in Slack bot mode with logs visible
run-slack-logs:
    podman run --rm --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/main.py

# Run CLI command in container
# Usage: just cli analyze https://jenkins.example.com/job/release/123/
# Usage: just cli info https://jenkins.example.com/job/release/123/
# Usage: just cli logs https://jenkins.example.com/job/release/123/
cli +args:
     podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py {{args}}

# Show CLI help
cli-help:
     podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py --help

# Analyze a Jenkins build (requires LLM API key)
# Usage: just analyze https://jenkins.example.com/job/release/123/
analyze url:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py analyze {{url}}

# Get build information
# Usage: just info https://jenkins.example.com/job/release/123/
info url:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py info {{url}}

# Get build logs
# Usage: just logs https://jenkins.example.com/job/release/123/
logs url:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py logs {{url}}

# List builds for a job
# Usage: just builds https://jenkins.example.com/job/release/123/
builds url limit="20":
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py builds {{url}} --limit {{limit}}

# Get pipeline status
status:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py status

# Get pipeline status as JSON
status-json:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py status --json

# Retry a Jenkins build
# Usage: just retry https://jenkins.example.com/job/release/123/
retry url:
    podman run --rm -v $(pwd):/app:z --env-file .env --entrypoint "python3" coreos-pipeline-assistant /app/cli.py retry {{url}}

# Clean up: remove container and image
clean:
    -podman rm -f coreos-pipeline-assistant
    -podman rmi coreos-pipeline-assistant