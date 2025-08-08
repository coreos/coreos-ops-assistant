import functools
import logging
import re
import requests
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List

from jenkins import Jenkins, JenkinsException

STREAM_MAPPING = {
    1: 'next',
    2: 'testing',
    3: 'stable',
    10: 'next-devel',
    20: 'testing-devel',
    91: 'rawhide',
    92: 'branched',
}

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

def parse_jenkins_url(url: str) -> tuple[str, int]:
    """Parses a Jenkins job URL to extract job name and build number.
    
    Args:
        url: Jenkins job URL like https://jenkins.example.com/job/my-job/123/
        
    Returns:
        Tuple of (job_name, build_number)
        
    Raises:
        ValueError: If URL format is invalid
    """
    match = re.search(r"https?://(.*?)/job/(.*?)/([0-9]+)", url)
    if not match:
        raise ValueError(f"Invalid Jenkins job URL format: {url}")
    
    job_name = match.group(2)
    build_number = int(match.group(3))
    return job_name, build_number

def get_build_from_url(jenkins_server: Jenkins, url: str) -> Build:
    """Gets Jenkins build information from a job URL.
    
    Args:
        jenkins_server: Jenkins client instance
        url: Jenkins job URL
        
    Returns:
        Build object with job information
    """
    job_name, build_number = parse_jenkins_url(url)
    return get_build_info(jenkins_server, job_name, build_number)

def get_build_info(jenkins_server: Jenkins, job_name: str, build_number: int) -> Build:
    """Gets information about a specific Jenkins build.
    
    Args:
        jenkins_server: Jenkins client instance
        job_name: Name of the Jenkins job
        build_number: Build number
        
    Returns:
        Build object with detailed information
    """
    logging.info(f"getting build info for {job_name} #{build_number}")
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

def get_jenkins_build_logs(jenkins_server: Jenkins, job_name: str, build_number: int) -> str:
    """Gets the Jenkins logs for a given Jenkins build.

    Args:
        jenkins_server: Jenkins client instance
        job_name: The name of the Jenkins job.
        build_number: The build number for which to retrieve the logs.

    Returns:
        The logs for the specified Jenkins build.
    """
    logging.info(f"getting build logs for job_name={job_name} build_number={build_number}")
    try:
        return jenkins_server.get_build_console_output(job_name, build_number)
    except JenkinsException as e:
        logging.error(f"Error fetching Jenkins logs: {e}")
        return f"Error fetching Jenkins logs: {e}"

def get_list_of_builds_for_job(jenkins_server: Jenkins, job_name: str) -> List[Build]:
    """Gets the list of builds for a given Jenkins job.

    Args:
        jenkins_server: Jenkins client instance
        job_name: The name of the Jenkins job.

    Returns:
        A list of Build objects for the specified Jenkins job.
    """
    logging.info(f"getting list of builds for job_name={job_name}")
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

def get_latest_successful_build_for_stream(jenkins_server: Jenkins, stream_name: str) -> Optional[Build]:
    """Gets the latest successful build of a given stream.

    Args:
        jenkins_server: Jenkins client instance
        stream_name: The name of the stream.

    Returns:
        A Build object containing details about the build, or None if not found.
    """
    logging.info(f"getting latest successful build for stream_name={stream_name}")
    builds = get_list_of_builds_for_job(jenkins_server, "release")
    for build in builds:
        if build.build_result != 'SUCCESS' or build.stream != stream_name:
            continue
        return build
    return None

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

def get_pipeline_status(jenkins_server: Jenkins) -> OrderedDict[str, StreamBuild]:
    """Gets the status of the Jenkins pipeline.

    Args:
        jenkins_server: Jenkins client instance

    Returns:
        A dictionary mapping the stream to a StreamBuild object.
    """
    logging.info("getting pipeline status")
    builds = get_list_of_builds_for_job(jenkins_server, "release")
    status: OrderedDict[str, StreamBuild] = OrderedDict()
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

def retry_jenkins_build(jenkins_server: Jenkins, job_name: str, build_number: int) -> str:
    """Retries a specific Jenkins build.

    Args:
        jenkins_server: Jenkins client instance
        job_name: The name of the Jenkins job.
        build_number: The build number to retry.

    Returns:
        A string indicating the success or failure of the retry operation.
    """
    logging.info(f"retrying {job_name} #{build_number}")
    return jenkins_server.retry_build(job_name, build_number)