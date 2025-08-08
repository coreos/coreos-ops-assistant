import logging
import re
from typing import Optional

from pydantic_ai import agent
from jenkins_core import (
    Build, get_build_info, get_jenkins_build_logs, get_list_of_builds_for_job,
    get_latest_successful_build_for_stream, get_rpms_for_build, 
    retry_jenkins_build, parse_jenkins_url
)

def create_agent_tools(jenkins_server, slack_app=None):
    """Creates agent tools that can be used with pydantic_ai Agent.
    
    Args:
        jenkins_server: Jenkins client instance
        slack_app: Optional Slack app instance (for Slack mode)
        
    Returns:
        List of agent tool functions
    """
    
    @agent.tool_plain
    def get_associated_jenkins_build(channel: str = "", thread_ts: Optional[str] = None, url: Optional[str] = None) -> Build:
        """Gets the Jenkins build that is best associated with a user query.

        Args:
            channel: The Slack channel (only used in Slack mode)
            thread_ts: The Slack thread timestamp, if called from a thread (only used in Slack mode)
            url: Direct Jenkins job URL (for standalone mode)

        Returns:
            A Build object containing information about the Jenkins build, including
            the job name, the build number, build result, build description, and
            build timestamp.
        """
        logging.info(f"get_associated_jenkins_build called for thread_ts={thread_ts}, url={url}")

        # If URL is provided directly (CLI mode), use it
        if url:
            try:
                job_name, build_number = parse_jenkins_url(url)
                return get_build_info(jenkins_server, job_name, build_number)
            except ValueError as e:
                logging.error(f"Invalid Jenkins URL: {e}")
                # Return empty build object
                from datetime import datetime
                from jenkins_core import _human_friendly_time_diff
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

        # Slack mode - requires slack_app
        if not slack_app:
            raise ValueError("slack_app is required for Slack mode operations")
            
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
        match = re.search(r"https://(.*?)/job/(.*?)/([0-9]+)", text)
        if not match:
            from datetime import datetime
            from jenkins_core import _human_friendly_time_diff
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
        
        return get_build_info(jenkins_server, job_name, build_number)

    @agent.tool_plain
    def get_jenkins_build_logs_tool(job_name: str, build_number: int) -> str:
        """Gets the Jenkins logs for a given Jenkins build.

        Args:
            job_name: The name of the Jenkins job.
            build_number: The build number for which to retrieve the logs.

        Returns:
            The logs for the specified Jenkins build.
        """
        return get_jenkins_build_logs(jenkins_server, job_name, build_number)

    @agent.tool_plain
    def get_list_of_builds_for_job_tool(job_name: str) -> list[Build]:
        """Gets the list of builds for a given Jenkins job.

        Args:
            job_name: The name of the Jenkins job.

        Returns:
            A list of Build objects for the specified Jenkins job.
        """
        return get_list_of_builds_for_job(jenkins_server, job_name)

    @agent.tool_plain
    def get_latest_successful_build_for_stream_tool(stream_name: str) -> Optional[Build]:
        """Gets the latest successful build of a given stream.

        Args:
            stream_name: The name of the stream.

        Returns:
            A Build object containing details about the build, or None if not found.
        """
        return get_latest_successful_build_for_stream(jenkins_server, stream_name)

    @agent.tool_plain
    def get_rpms_for_build_tool(build_version: str, build_architecture: Optional[str] = None) -> dict[str, str]:
        """Gets the list of RPM packages and their versions for a given build version.

        Args:
            build_version: The version of the build.
            build_architecture: The architecture of the build. Optional. Defaults to x86_64 if missing.

        Returns:
            A dictionary of package name to package version.
        """
        return get_rpms_for_build(build_version, build_architecture)

    @agent.tool_plain
    def retry_jenkins_build_tool(job_name: str, build_number: int) -> str:
        """Retries a specific Jenkins build.

        Args:
            job_name: The name of the Jenkins job.
            build_number: The build number to retry.

        Returns:
            A string indicating the success or failure of the retry operation.
        """
        return retry_jenkins_build(jenkins_server, job_name, build_number)

    return [
        get_associated_jenkins_build,
        get_jenkins_build_logs_tool,
        get_list_of_builds_for_job_tool,
        get_latest_successful_build_for_stream_tool,
        get_rpms_for_build_tool,
        retry_jenkins_build_tool
    ]