import logging
import os
from collections import OrderedDict
from typing import Optional

from jenkins import Jenkins
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App

# We support connecting to Gemini directly or to OpenRouter (for
# access to a large selection of LLMs).
from pydantic_ai import Agent
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

from agent_tools import create_agent_tools

# just globally set this
FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)

# Check for required environment variables
required_env_vars = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "JENKINS_URL", "JENKINS_TOKEN"]
missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")

# initialize Slack, Gemini, and Jenkins
slack_app = App(token=os.environ["SLACK_BOT_TOKEN"])

jenkins_server = Jenkins(url=os.environ["JENKINS_URL"],
                         token=os.environ["JENKINS_TOKEN"])

thread_chats: OrderedDict[str, list] = OrderedDict() # str -> list of messages

# system instruction we pass to the LLM
system_instruction = """
You are a member of the CoreOS team, tasked with monitoring the Jenkins
pipeline which builds, tests, and releases RHEL CoreOS artifacts. Users will
ping you with requests related to this pipeline within a room in Slack in which
notifications from Jenkins builds are delivered. Answer user requests to the
best of your ability using the tools at your disposal. You are friendly but
succinct.
"""

# Initialize the LLM with pydantic_ai. Either Gemini directly or OpenRouter.
# We select here based on the which tokens are available in the environment,
# either $GEMINI_API_KEY or $OPENROUTER_API_KEY.
if os.environ.get('GEMINI_API_KEY', ''):
    model = GeminiModel('gemini-2.5-flash', provider='google-gla')
elif os.environ.get('OPENROUTER_API_KEY', ''):
    model = OpenAIModel(
        'google/gemini-2.5-flash-preview-05-20',
        provider=OpenRouterProvider(api_key=os.environ.get('OPENROUTER_API_KEY'))
    )
else:
    raise Exception("Must set GEMINI_API_KEY or OPENROUTER_API_KEY env var")

# Create agent with tools
tools = create_agent_tools(jenkins_server, slack_app)
agent = Agent(
    system_prompt=system_instruction,
    model=model,
    tools=tools,
)



@slack_app.event("app_mention")
def handle_app_mention_events(body, logger, say):
    logger.info(body)
    event = body["event"]
    channel = event["channel"]

    slack_app.client.reactions_add(channel=channel, name='hourglass_flowing_sand', timestamp=event["ts"])

    pre_prompt = f"You were just pinged in channel {channel} by a user "

    thread_ts = event.get("thread_ts")
    if thread_ts:
        # presumably we should just make a context object or closure instead
        # from our tools but let's see how well this works...
        pre_prompt += f" from within a thread with thread_ts={thread_ts}. "
    else:
        pre_prompt += " from outside of a thread. "
    pre_prompt += "Here is the user's message: "

    user_prompt = strip_userid(event['text'])
    if user_prompt == "":
        logger.info("got empty command; ignoring...")
        return

    # If in a thread, manage message history using the global thread_chats dict.
    # Otherwise, use empty message history for single messages.
    if thread_ts:
        if thread_ts not in thread_chats:
            thread_chats[thread_ts] = []
        message_history = thread_chats[thread_ts]
    else:
        message_history = []

    result = agent.run_sync(pre_prompt + user_prompt, message_history=message_history)
    message_history.extend(result.new_messages())

    say(text=result.output, thread_ts=thread_ts or event["ts"])
    slack_app.client.reactions_remove(channel=channel, name='hourglass_flowing_sand', timestamp=event["ts"])


# Convert '<@USERID> msg' to 'msg'
def strip_userid(msg: str):
    elems = msg.split(' ', 1)
    if not elems[0].startswith('<@'):
        return msg.strip()
    if len(elems) > 1:
        return elems[1].strip()
    return ''


if __name__ == "__main__":
    SocketModeHandler(slack_app, os.environ["SLACK_APP_TOKEN"]).start()
