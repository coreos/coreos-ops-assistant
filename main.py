import asyncio
import functools
import logging
import nest_asyncio
import os
import pprint
import re
import requests

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List

from jenkins import Jenkins, JenkinsException
from nio import RoomMessage
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App

# We support connecting to Gemini directly or to OpenRouter (for
# access to a large selection of LLMs).
from pydantic_ai import Agent, agent
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

# We support either Slack Or Matrix
from chat_platform import SlackPlatform, MatrixPlatform

STREAM_MAPPING = {
    1: 'next',
    2: 'testing',
    3: 'stable',
    10: 'next-devel',
    20: 'testing-devel',
    91: 'rawhide',
    92: 'branched',
}

# just globally set this
FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)

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
agent = Agent(
    system_prompt=system_instruction,
    model=model,
)

class BuildResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNSTABLE = "UNSTABLE"


@dataclass
class Build:
    """Represents a Jenkins build."""
    job_name: str
    build_number: int
    build_description: Optional[str]
    build_result: Optional[str]
    timestamp: datetime
    relative_timestamp: str
    build_version: Optional[str]
    architectures: Optional[List[str]] = None
    stream: Optional[str] = None


def _human_friendly_time_diff(timestamp: datetime) -> str:
    """Calculates a human-friendly relative time difference."""
    now = datetime.now()
    diff = now - timestamp

    if diff.days > 0:
        return f"{diff.days} days ago"
    elif diff.seconds >= 3600:  # hours
        hours = diff.seconds // 3600
        return f"{hours} hours ago"
    elif diff.seconds >= 60:  # minutes
        minutes = diff.seconds // 60
        return f"{minutes} minutes ago"
    else:
        return "just now"


class StreamStatus(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class StreamBuild:
    """Represents the last successful build for a stream."""
    build: Optional[Build]
    build_version: Optional[str] = None
    status: Optional[str] = None


@agent.tool_plain
def get_associated_jenkins_build(channel: str, event_id: str, thread_id: Optional[str] = None) -> Build:
    """Gets the Jenkins build that is best associated with a user query.

    Args:
        channel: The Slack channel
        event_id: The id of the user message triggering this request.
        thread_id: The id of the thread, if called from a thread.

    Returns:
        A Build object containing information about the Jenkins build, including
        the job name, the build number, build result, build description, and
        build timestamp.
    """
    logging.info(f"get_associated_jenkins_build called for event_id={event_id} thread_id={thread_id}")

    # Get the starting message for the conversation
    message = chat_platform.get_message(channel=channel, event_id=thread_id or event_id)

    logging.info(f"message in get_associated_jenkins_build: {message}")

    match = re.search(r"https://(.*?)/job/(.*?)/([0-9]+)", message)
    if not match:
        return Build(
            job_name="",
            build_number=0,
            build_description=None,
            build_result=None,
            timestamp=datetime.now(),
            relative_timestamp=_human_friendly_time_diff(datetime.now()),
            build_version=None,
            architectures=None,
            stream=None
        )

    job_name = match.group(2)
    build_number = int(match.group(3))
    logging.info(f"calling get_build_info for {job_name} #{build_number}")
    try:
        b = jenkins_server.get_build_info(job_name, build_number)
        logging.info(f"INFO: got build info: {pprint.pformat(b)}")
        _timestamp = datetime.fromtimestamp(b['timestamp'] / 1000)

        # Extract stream and architectures
        desc = b.get('description') or ""
        stream_match = re.search(r"\[(.*?)\]", desc)
        stream = stream_match.group(1) if stream_match else None

        arch_match = re.search(r"\[.*?\]\s*\[(.*?)\]", desc)
        architectures = arch_match.group(1).split() if arch_match else None

        # Extract build version
        version_match = re.search(r"(\d+\.\d+(?:\.\d+)*)", desc)
        build_version = version_match.group(1) if version_match else None

    except JenkinsException as e:
        logging.warn(f"got exception: {e}")
        raise e

    return Build(
        job_name=job_name,
        build_number=b['number'],
        build_description=b.get('description'),
        build_result=b.get('result'),
        timestamp=_timestamp,
        relative_timestamp=_human_friendly_time_diff(_timestamp),
        build_version=build_version,
        architectures=architectures,
        stream=stream
    )


@agent.tool_plain
def get_jenkins_build_logs(job_name: str, build_number: int) -> str:
    """Gets the Jenkins logs for a given Jenkins build.

    Args:
        job_name: The name of the Jenkins job.
        build_number: The build number for which to retrieve the logs.

    Returns:
        The logs for the specified Jenkins build.
    """
    logging.info(f"get_jenkins_build_logs called for job_name={job_name} build_number={build_number}")
    try:
        return jenkins_server.get_build_console_output(job_name, build_number)
    except JenkinsException as e:
        logging.error(f"Error fetching Jenkins logs: {e}")
        return f"Error fetching Jenkins logs: {e}"


@agent.tool_plain
def get_list_of_builds_for_job(job_name: str) -> List[Build]:
    """Gets the list of builds for a given Jenkins job.

    Args:
        job_name: The name of the Jenkins job.

    Returns:
        A list of Build objects for the specified Jenkins job.
    """
    logging.info(f"get_list_of_builds_for_job called for job_name={job_name}")
    builds = []
    try:
        job_info = jenkins_server.get_job_info(job_name, depth=1)
        for b in job_info['builds']:
            _timestamp = datetime.fromtimestamp(b['timestamp'] / 1000)
            desc = b.get('description') or ""

            # Extract stream, architectures, and version
            stream_match = re.search(r"\[(.*?)\]", desc)
            stream = stream_match.group(1) if stream_match else None

            arch_match = re.search(r"\[.*?\]\s*\[(.*?)\]", desc)
            architectures = arch_match.group(1).split() if arch_match else None

            version_match = re.search(r"(\d+\.\d+(?:\.\d+)*)", desc)
            build_version = version_match.group(1) if version_match else None

            builds.append(Build(
                job_name=job_name,
                build_number=b['number'],
                build_description=desc,
                build_result=b.get('result'),
                timestamp=_timestamp,
                relative_timestamp=_human_friendly_time_diff(_timestamp),
                build_version=build_version,
                architectures=architectures,
                stream=stream
            ))
        return builds
    except JenkinsException as e:
        logging.error(f"Error fetching Jenkins builds for job {job_name}: {e}")
        return []


@agent.tool_plain
def get_latest_successful_build_for_stream(stream_name: str) -> Build:
    """Gets the latest successful build of a given stream.

    Args:
        stream_name: The name of the stream.

    Returns:
        A Build object containing details about the build.
    """
    logging.info(f"called for stream_name={stream_name}")
    builds = get_list_of_builds_for_job("release")
    for build in builds:
        if build.build_result != 'SUCCESS' or build.stream != stream_name:
            continue
        return build


@agent.tool_plain
def get_rpms_for_build(build_version: str, build_architecture: Optional[str] = None) -> dict[str, str]:
    """Gets the list of RPM packages and their versions for a given build version.

    Args:
        build_version: The version of the build.
        build_architecture: The architecture of the build. Optional. Defaults to x86_64 if missing.

    Returns:
        A dictionary of package name to package version.
    """

    logging.info(f"Fetching RPMs for version={build_version}, arch={build_architecture}")
    return get_cached_rpms_for_build(build_version, build_architecture)


@functools.lru_cache()
def get_cached_rpms_for_build(build_version: str, build_architecture: Optional[str] = None) -> dict[str, str]:
    stream = STREAM_MAPPING[int(build_version.split('.')[2])]
    architecture = build_architecture if build_architecture else "x86_64"
    url = f"https://builds.coreos.fedoraproject.org/prod/streams/{stream}/builds/{build_version}/{architecture}/commitmeta.json"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        commitmeta = response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching commitmeta.json from {url}: {e}")
        return {}

    pkgs = {}
    for pkg in commitmeta['rpmostree.rpmdb.pkglist']:
        pkgs[pkg[0]] = f"{pkg[1]}:{pkg[2]}-{pkg[3]}.{pkg[4]}"
    return pkgs


def get_pipeline_status() -> OrderedDict[str, StreamBuild]:
    """Gets the status of the Jenkins pipeline.

    Returns:
        A dictionary mapping the stream to a StreamBuild object.
    """
    logging.info("get_pipeline_status called")
    builds = get_list_of_builds_for_job("release")
    status: OrderedDict[str, StreamBuild] = {}
    for build in builds:
        if build.build_result != 'SUCCESS' or not build.stream:
            continue

        stream = build.stream

        # Optimization: If we've already found the most recent valid build for
        # this stream, skip older ones.
        if stream in status:
            continue

        stream_build_obj = StreamBuild(build=build,
                                       build_version=build.build_version,
                                       status=None)

        # Determine StreamStatus based on build age
        now = datetime.now()
        time_since_build = now - build.timestamp

        # XXX: This doesn't really map well to how FCOS works since prod
        # streams release every 2 weeks. Probably cleaner to just only filter in
        # mechanical and development builds (i.e. builds that are automated).
        if time_since_build < timedelta(hours=36):
            stream_build_obj.status = StreamStatus.GREEN.value
        elif time_since_build < timedelta(hours=72):
            stream_build_obj.status = StreamStatus.YELLOW.value
        else:
            stream_build_obj.status = StreamStatus.RED.value

        logging.info(f"Stream: {stream}, Build: {build.build_number}, Time Since Build: {time_since_build}, Calculated Status: {stream_build_obj.status}")
        status[stream] = stream_build_obj

    # Sort the status by the timestamp of the build in descending order (most recent first)
    sorted_status = OrderedDict(sorted(status.items(), key=lambda item: item[1].build.timestamp, reverse=True))
    return sorted_status


@agent.tool_plain
def retry_jenkins_build(job_name: str, build_number: int) -> str:
    """Retries a specific Jenkins build.

    Args:
        job_name: The name of the Jenkins job.
        build_number: The build number to retry.

    Returns:
        A string indicating the success or failure of the retry operation.
    """
    logging.info(f"called to retry {job_name} #{build_number}")
    return jenkins_server.retry_build(job_name, build_number)


def process_message(channel, event_id, thread_id, text=''):
    pre_prompt = ""
    user_prompt = strip_userid(text)
    if user_prompt == "":
        logger.info("got empty command; ignoring...")
        return

    if thread_id and thread_id in thread_chats:
        pass # Thread has already been initialized. Can skip pre_prompt.
    else:
        pre_prompt = f"You were just pinged in channel=\"{channel}\" by a user "
        pre_prompt += f"in a message with event_id=\"{event_id}\". This message is"
        if thread_id:
            # presumably we should just make a context object or closure instead
            # from our tools but let's see how well this works...
            pre_prompt += f" from within a thread with thread_id=\"{thread_id}\". "
        else:
            pre_prompt += " from outside of a thread. "
        pre_prompt += "Here is the user's message: "


    # If in a thread, manage message history using the global thread_chats dict.
    # Otherwise, use empty message history for single messages.
    if thread_id:
        if thread_id not in thread_chats:
            thread_chats[thread_id] = []
        message_history = thread_chats[thread_id]
    else:
        thread_chats[event_id] = []
        message_history = thread_chats[event_id]

    # Garbage collect so we don't grow boundlessly
    if len(thread_chats) > 30:
        thread_chats.popitem(last=False)

    logging.info(f"INFO: {pre_prompt} {user_prompt}")
    result = agent.run_sync(pre_prompt + user_prompt, message_history=message_history)
    message_history.extend(result.new_messages())
    return result



# Convert '<@USERID> msg' to 'msg' (Slack) or '@user:matrix.org msg' to 'msg' (Matrix)
def strip_userid(msg: str):
    elems = msg.split(' ', 1)
    if not elems[0].startswith('<@') and not elems[0].startswith('@'):
        return msg.strip()
    if len(elems) > 1:
        return elems[1].strip()
    return ''


if __name__ == "__main__":
    matrix_server = os.environ.get("MATRIX_SERVER", '')
    matrix_access_token = os.environ.get("MATRIX_ACCESS_TOKEN", '')
    matrix_room = os.environ.get("MATRIX_ROOM", '')
    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", '')
    slack_app_token = os.environ.get("SLACK_APP_TOKEN", '')

    matrix_defined = matrix_server and matrix_access_token and matrix_room
    slack_defined = slack_bot_token and slack_app_token

    if matrix_defined and slack_defined:
        raise ValueError("Env vars for matrix and slack are set. Can't target both at the same time.")
    elif not slack_defined and not matrix_defined:
        raise ValueError("Must set environment vars to choose a chat platform. See README")

    if slack_defined:
        logging.info("Running in Slack mode.")
        chat_platform = SlackPlatform(slack_bot_token, process_message_func=process_message)
        handler = SocketModeHandler(chat_platform.slack_app, slack_app_token)
        handler.app.event("app_mention")(chat_platform.handle_app_mention_events)
        handler.start()
    else:
        logging.info("Running in Matrix mode.")
        nest_asyncio.apply() # Apply nest_asyncio to allow nested event loops
        chat_platform = MatrixPlatform(matrix_server, matrix_access_token,
                matrix_room, process_message_func=process_message)
        # Register a callback to be called when we receive new messages
        chat_platform.client.add_event_callback(
            chat_platform.monitor_messages, RoomMessage)
        try:
            asyncio.run(chat_platform.client.sync_forever(full_state=True))
        finally:
            asyncio.run(chat_platform.client.close())
