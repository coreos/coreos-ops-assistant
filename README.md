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

For Jenkins:

    *   `JENKINS_URL`: The URL of your Jenkins server.
    *   `JENKINS_TOKEN`: Your Jenkins token (often an API token).

If using Slack:

    *   `SLACK_BOT_TOKEN`: Your Slack bot token.
    *   `SLACK_APP_TOKEN`: Your Slack app token.

If using Matrix:

    *   `MATRIX_SERVER`: Your homeserver (i.e.  https://matrix.org)
    *   `MATRIX_ACCESS_TOKEN`: Your device access token
    *   `MATRIX_ROOM`: Your room FQDN (i.e. `#tmp-coreos-pipeline-assistant-testing:matrix.org`)

If using GEMINI:

    *   `GEMINI_API_KEY`: (OPTIONAL) Your Gemini API key.

If using OpenRouter:

    *   `OPENROUTER_API_KEY`: (OPTIONAL) Your OpenRouter access key

## Usage

1.  **Run the bot:**
    ```
    source env.sh            # tokens env vars
    source env/bin/activate  # if using a virtualenv
    python main.py
    ```

2.  **Invite the bot to your Slack channel.**

3.  **Mention the bot in a thread of a Jenkins failure notification.** The bot will then reply with a summary of the failure.

### Running with Podman

1.  **Build the container image:**
    ```
    podman build -t coreos-pipeline-assistant .
    ```

2.  **Run the container:**
    You can pass the environment variables directly with the `-e` flag, or you can use a `.env` file.


    **Using the `-e` flag:**
    ```
    # First export the appropriate variables in your environment based
    # on what you are using (i.e. slack/matrix and gemini/openrouter)
    export SLACK_BOT_TOKEN='your_bot_token'
    export SLACK_APP_TOKEN='your_app_token'
    export MATRIX_SERVER='https://matrix.org'
    export MATRIX_ACCESS_TOKEN='your_app_token'
    export MATRIX_ROOM='your_room_fqdn'
    export JENKINS_URL='https://your.jenkins.url'
    export JENKINS_TOKEN='your_jenkins_token'
    export GEMINI_API_KEY='your_api_key'
    export OPENROUTER_API_KEY='your_api_key'

    # Now run `podman` and it will pull the values from the variables
    # already set in your environment.
    podman run -it --rm        \
      -e SLACK_BOT_TOKEN       \
      -e SLACK_APP_TOKEN       \
      -e MATRIX_SERVER         \
      -e MATRIX_ACCESS_TOKEN   \
      -e MATRIX_ROOM           \
      -e JENKINS_URL           \
      -e JENKINS_TOKEN         \
      -e GEMINI_API_KEY        \
      -e OPENROUTER_API_KEY    \
      coreos-pipeline-assistant
    ```

    **Using a `.env` file:**
    Create a file named `.env` with the following content:
    ```
    SLACK_BOT_TOKEN=your_bot_token
    SLACK_APP_TOKEN=your_app_token
    MATRIX_SERVER=https://matrix.org
    MATRIX_ACCESS_TOKEN=your_app_token
    MATRIX_ROOM=your_room_fqdn
    JENKINS_URL=https://your.jenkins.url
    JENKINS_TOKEN=your_jenkins_token
    GEMINI_API_KEY=your_api_key
    OPENROUTER_API_KEY=your_api_key
    ```
    Then run the container with the `--env-file` flag:
    ```
    podman run -it --rm --env-file .env coreos-pipeline-assistant
    ```

## Testing

To run the unit tests, run the following command from the root of the project:
```
python3 test.py
```
