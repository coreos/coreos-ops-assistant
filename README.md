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
    *   `GEMINI_API_KEY`: Your Gemini API key.

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
    podman run -it --rm \
      -e SLACK_BOT_TOKEN='your_bot_token' \
      -e SLACK_APP_TOKEN='your_app_token' \
      -e JENKINS_URL='https://your.jenkins.url' \
      -e JENKINS_TOKEN='your_jenkins_token' \
      -e GEMINI_API_KEY='your_gemini_api_key' \
      coreos-pipeline-assistant
    ```

    **Using a `.env` file:**
    Create a file named `.env` with the following content:
    ```
    SLACK_BOT_TOKEN='your_bot_token'
    SLACK_APP_TOKEN='your_app_token'
    JENKINS_URL='https://your.jenkins.url'
    JENKINS_TOKEN='your_jenkins_token'
    GEMINI_API_KEY='your_gemini_api_key'
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
