# CoreOS Pipeline Assistant

This is an AI-powered assistant used by the CoreOS team to make pipeline monitoring easier.
Currently, it only works in Slack, but in the future it will also be pluggable into Matrix.

The assistant listens for direct mentions in a Slack channel in which it was invited.

Currently, it can:
- retrieve overall pipeline health status
- retrieve generic build information (stream, version, architectures, status)
- retrieve build logs, analyze them, and provide a summary of failures
- retry builds

## Setup

### Local Python Environment

1.  **Install dependencies:**
    ```
    source env/bin/activate  # if using a virtualenv
    pip install -r requirements.txt
    ```

2.  **Set environment variables:**
    *   `SLACK_BOT_TOKEN`: Your Slack bot token.
    *   `SLACK_APP_TOKEN`: Your Slack app token.
    *   `JENKINS_URL`: The URL of your Jenkins server.
    *   `JENKINS_TOKEN`: Your Jenkins token (often an API token).
    *   `GEMINI_API_KEY`: (OPTIONAL) Your Gemini API key.
    *   `OPENROUTER_API_KEY`: (OPTIONAL) Your OpenRouter access key

## Usage

### Standalone CLI Mode

The tool can now run as a standalone CLI application for analyzing Jenkins builds without requiring Slack integration.

#### Local Python Environment

1.  **Install dependencies:**
    ```bash
    # Using uv (recommended)
    uv venv && source .venv/bin/activate
    uv pip install -r requirements.txt
    
    # Or using pip
    pip install -r requirements.txt
    ```

2.  **Set environment variables:**
    ```bash
    export JENKINS_URL="https://your.jenkins.url"
    export JENKINS_TOKEN="your_jenkins_token"
    export GEMINI_API_KEY="your_api_key"  # Optional, for analysis
    ```

3.  **Run CLI commands:**
    ```bash
    # Analyze a build with AI
    python3 cli.py analyze https://jenkins.example.com/job/release/123/
    
    # Get build information
    python3 cli.py info https://jenkins.example.com/job/release/123/
    
    # Get build logs
    python3 cli.py logs https://jenkins.example.com/job/release/123/
    
    # List recent builds
    python3 cli.py builds https://jenkins.example.com/job/release/123/ --limit 10
    
    # Get overall pipeline status
    python3 cli.py status
    
    # Get RPM packages for a build
    python3 cli.py rpms --version 40.20240101.1.0 --arch x86_64
    ```

#### Using Justfile (Recommended)

The project includes a Justfile with convenient recipes for container-based usage:

1.  **Setup environment:**
    ```bash
    just create-env    # Creates .env.example
    cp .env.example .env
    # Edit .env with your actual values
    ```

2.  **Build container:**
    ```bash
    just build
    ```

3.  **Run CLI commands:**
    ```bash
    # Analyze a build
    just analyze https://jenkins.example.com/job/release/123/
    
    # Get build info
    just info https://jenkins.example.com/job/release/123/
    
    # Get logs
    just logs https://jenkins.example.com/job/release/123/
    
    # List builds
    just builds https://jenkins.example.com/job/release/123/
    
    # Pipeline status
    just status
    just status-json
    
    # RPM packages
    just rpms 40.20240101.1.0
    just rpms-from-build https://jenkins.example.com/job/release/123/
    ```

4.  **See all available commands:**
    ```bash
    just --list
    just show-env
    ```

### Slack Bot Mode

1.  **Run the bot locally:**
    ```bash
    source env.sh            # tokens env vars
    source .venv/bin/activate  # if using uv/venv
    python main.py
    ```

2.  **Run with Justfile:**
    ```bash
    just run-slack
    ```

3.  **Invite the bot to your Slack channel.**

4.  **Mention the bot in a thread of a Jenkins failure notification.** The bot will then reply with a summary of the failure.

### Container Usage

The container supports both modes automatically based on the command arguments:

#### Manual Podman Commands

**Slack mode (default):**
```bash
podman run -it --rm --env-file .env coreos-pipeline-assistant
```

**CLI mode:**
```bash
podman run --rm --env-file .env coreos-pipeline-assistant analyze https://jenkins.../job/release/123/
podman run --rm --env-file .env coreos-pipeline-assistant info https://jenkins.../job/release/123/
```

#### With Justfile (Recommended)

Use the Justfile recipes for much simpler commands - see the Justfile section above.

## Testing

To run the unit tests, run the following command from the root of the project:
```
python3 test.py
```
