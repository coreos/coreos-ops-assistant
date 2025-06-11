import logging
import os
import re

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List

from google.genai import types
from google import genai
from jenkins import Jenkins, JenkinsException
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App

# just globally set this
logging.basicConfig(level=logging.INFO)

# initialize Slack, Gemini, and Jenkins
slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
jenkins_server = Jenkins(url=os.environ["JENKINS_URL"],
                         token=os.environ["JENKINS_TOKEN"])

thread_chats: OrderedDict[str, genai.chats.Chat] = OrderedDict()

# system instruction we pass to Gemini
system_instruction = """
You are a member of the CoreOS team, tasked with monitoring the Jenkins
pipeline which builds, tests, and releases RHEL CoreOS artifacts. Users will
ping you with requests related to this pipeline within a room in Slack in which
notifications from Jenkins builds are delivered. Answer user requests to the
best of your ability using the tools at your disposal. You are friendly but
succinct.
"""


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
    status: Optional[StreamStatus] = None


def get_associated_jenkins_build(channel: str, thread_ts: Optional[str] = None) -> Build:
    """Gets the Jenkins build that is best associated with a user query.

    Args:
        channel: The Slack channel
        thread_ts: The Slack thread timestamp, if called from a thread.

    Returns:
        A Build object containing information about the Jenkins build, including
        the job name, the build number, build result, build description, and
        build timestamp.
    """
    logging.info(f"called for thread_ts={thread_ts}")

    if thread_ts:
        # we were mentioned in a thread; get the parent of the thread
        result = slack_app.client.conversations_history(
            channel=channel,
            latest=thread_ts,
            inclusive=True,
            limit=1
        )
        message = result["messages"][0]
    else:
        # get the latest message in the channel
        result = slack_app.client.conversations_history(
            channel=channel,
            limit=1
        )
        message = result["messages"][0]

    text = message["text"]
    # Updated regex to capture stream, architectures, and version
    match = re.search(r"https://(.*?)/job/(.*?)/(.*?)/", text)
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


def get_jenkins_build_logs(job_name: str, build_number: int) -> str:
    """Gets the Jenkins logs for a given Jenkins build.

    Args:
        job_name: The name of the Jenkins job.
        build_number: The build number for which to retrieve the logs.

    Returns:
        The logs for the specified Jenkins build.
    """
    logging.info(f"called for job_name={job_name} build_number={build_number}")
    try:
        return jenkins_server.get_build_console_output(job_name, build_number)
    except JenkinsException as e:
        logging.error(f"Error fetching Jenkins logs: {e}")
        return f"Error fetching Jenkins logs: {e}"


def get_list_of_builds_for_job(job_name: str) -> List[Build]:
    """Gets the list of builds for a given Jenkins job.

    Args:
        job_name: The name of the Jenkins job.

    Returns:
        A list of Build objects for the specified Jenkins job.
    """
    logging.info(f"called for job_name={job_name}")
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


def get_pipeline_status() -> OrderedDict[str, StreamBuild]:
    """Gets the status of the Jenkins pipeline.

    Returns:
        A dictionary mapping the stream to a StreamBuild object.
    """
    logging.info("called")
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
            stream_build_obj.status = StreamStatus.GREEN
        elif time_since_build < timedelta(hours=72):
            stream_build_obj.status = StreamStatus.YELLOW
        else:
            stream_build_obj.status = StreamStatus.RED

        logging.debug(f"Stream: {stream}, Build: {build.build_number}, Time Since Build: {time_since_build}, Calculated Status: {stream_build_obj.status}")
        status[stream] = stream_build_obj

    # Sort the status by the timestamp of the build in descending order (most recent first)
    sorted_status = OrderedDict(sorted(status.items(), key=lambda item: item[1].build.timestamp, reverse=True))
    return sorted_status


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


# Now that we're defined all the utility functions, let's set up the Gemini
# config! This doesn't need to be global, but it's basically not going to change
# for the duration of this execution.
gemini_config = types.GenerateContentConfig(
    tools=[get_associated_jenkins_build,
           get_jenkins_build_logs,
           get_pipeline_status,
           retry_jenkins_build],
    system_instruction=system_instruction,
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

    # If in a thread, manage chat history using the global thread_chats dict.
    # Otherwise, create a new chat for single messages.
    if thread_ts:
        if thread_ts not in thread_chats:
            # Remove oldest if dict size exceeds 30
            if len(thread_chats) >= 30:
                thread_chats.popitem(last=False)
            thread_chats[thread_ts] = gemini_client.chats.create(
                model="gemini-2.5-flash-preview-05-20",
                config=gemini_config,
            )
        chat = thread_chats[thread_ts]
    else:
        chat = gemini_client.chats.create(
            model="gemini-2.5-flash-preview-05-20",
            config=gemini_config,
        )

    # Send the user's message to the appropriate chat
    response = chat.send_message(pre_prompt + strip_userid(event['text']))

    say(text=response.text, thread_ts=thread_ts or event["ts"])
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
