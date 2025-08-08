#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
from typing import Optional

from jenkins import Jenkins
from jenkins_core import (
    get_build_from_url, get_jenkins_build_logs, get_list_of_builds_for_job,
    get_latest_successful_build_for_stream, get_rpms_for_build, 
    get_pipeline_status, retry_jenkins_build, parse_jenkins_url
)

# We support connecting to Gemini directly or to OpenRouter (for
# access to a large selection of LLMs).
from pydantic_ai import Agent
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

# Set up logging
FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
logging.basicConfig(level=logging.INFO, format=FORMAT)

def setup_jenkins_client() -> Jenkins:
    """Initialize Jenkins client from environment variables."""
    jenkins_url = os.environ.get("JENKINS_URL")
    jenkins_token = os.environ.get("JENKINS_TOKEN")
    verify_ssl = os.environ.get("JENKINS_VERIFY_SSL", "true").lower() == "true"
    
    if not jenkins_url or not jenkins_token:
        print("Error: JENKINS_URL and JENKINS_TOKEN environment variables are required")
        sys.exit(1)
    
    return Jenkins(url=jenkins_url, token=jenkins_token, verify_ssl=verify_ssl)

def setup_llm_agent() -> Optional[Agent]:
    """Initialize LLM agent if API keys are available."""
    system_instruction = """
You are a member of the CoreOS team, tasked with monitoring the Jenkins
pipeline which builds, tests, and releases RHEL CoreOS artifacts. Analyze
the provided Jenkins build information and logs to help identify issues
and provide insights. You are friendly but succinct.
"""
    
    if os.environ.get('GEMINI_API_KEY', ''):
        model = GeminiModel('gemini-2.5-flash', provider='google-gla')
    elif os.environ.get('OPENROUTER_API_KEY', ''):
        model = OpenAIModel(
            'google/gemini-2.5-flash-preview-05-20',
            provider=OpenRouterProvider(api_key=os.environ.get('OPENROUTER_API_KEY'))
        )
    else:
        return None
    
    return Agent(
        system_prompt=system_instruction,
        model=model,
    )

def cmd_analyze(args):
    """Analyze a Jenkins build using LLM."""
    jenkins_client = setup_jenkins_client()
    agent = setup_llm_agent()
    
    if not agent:
        print("Error: GEMINI_API_KEY or OPENROUTER_API_KEY required for analysis")
        sys.exit(1)
    
    try:
        # Get build information
        build = get_build_from_url(jenkins_client, args.url)
        
        # Get logs if requested or if build failed
        include_logs = args.logs or build.build_result in ['FAILURE', 'UNSTABLE']
        logs = ""
        if include_logs:
            logs = get_jenkins_build_logs(jenkins_client, build.job_name, build.build_number)
            # Truncate very long logs for LLM processing
            if len(logs) > 50000:
                logs = logs[-50000:]  # Keep last 50k characters
        
        # Prepare context for LLM
        context = f"""
Build Information:
- Job: {build.job_name}
- Build Number: {build.build_number}
- Result: {build.build_result}
- Description: {build.build_description}
- Timestamp: {build.timestamp} ({build.relative_timestamp})
- Stream: {build.stream}
- Architectures: {build.architectures}
- Version: {build.build_version}

"""
        
        if logs:
            context += f"\nBuild Logs:\n{logs}"
        else:
            context += "\nNo logs included in analysis."
        
        # Run LLM analysis
        prompt = f"Analyze this Jenkins build and provide insights: {context}"
        result = agent.run_sync(prompt)
        
        print("=== Build Analysis ===")
        print(result.output)
        
    except Exception as e:
        print(f"Error analyzing build: {e}")
        sys.exit(1)

def cmd_logs(args):
    """Get build logs."""
    jenkins_client = setup_jenkins_client()
    
    try:
        job_name, build_number = parse_jenkins_url(args.url)
        logs = get_jenkins_build_logs(jenkins_client, job_name, build_number)
        print(logs)
    except Exception as e:
        print(f"Error fetching logs: {e}")
        sys.exit(1)

def cmd_info(args):
    """Get build information."""
    jenkins_client = setup_jenkins_client()
    
    try:
        build = get_build_from_url(jenkins_client, args.url)
        
        print(f"Job Name: {build.job_name}")
        print(f"Build Number: {build.build_number}")
        print(f"Result: {build.build_result}")
        print(f"Description: {build.build_description}")
        print(f"Timestamp: {build.timestamp} ({build.relative_timestamp})")
        print(f"Stream: {build.stream}")
        print(f"Architectures: {build.architectures}")
        print(f"Version: {build.build_version}")
        
    except Exception as e:
        print(f"Error fetching build info: {e}")
        sys.exit(1)

def cmd_builds(args):
    """List builds for a job."""
    jenkins_client = setup_jenkins_client()
    
    try:
        job_name, _ = parse_jenkins_url(args.url)
        builds = get_list_of_builds_for_job(jenkins_client, job_name)
        
        if args.json:
            # Output as JSON
            builds_data = []
            for build in builds:
                builds_data.append({
                    'job_name': build.job_name,
                    'build_number': build.build_number,
                    'result': build.build_result,
                    'description': build.build_description,
                    'timestamp': build.timestamp.isoformat(),
                    'relative_timestamp': build.relative_timestamp,
                    'stream': build.stream,
                    'architectures': build.architectures,
                    'version': build.build_version
                })
            print(json.dumps(builds_data, indent=2))
        else:
            # Human-readable output
            print(f"Builds for job: {job_name}")
            print("=" * 50)
            for build in builds[:args.limit]:
                status_icon = "✅" if build.build_result == "SUCCESS" else "❌" if build.build_result == "FAILURE" else "⚠️"
                print(f"{status_icon} #{build.build_number} - {build.build_result} - {build.relative_timestamp}")
                if build.build_description:
                    print(f"   {build.build_description}")
                print()
                
    except Exception as e:
        print(f"Error fetching builds: {e}")
        sys.exit(1)

def cmd_status(args):
    """Get pipeline status."""
    jenkins_client = setup_jenkins_client()
    
    try:
        status = get_pipeline_status(jenkins_client)
        
        if args.json:
            # Output as JSON
            status_data = {}
            for stream, stream_build in status.items():
                status_data[stream] = {
                    'build_number': stream_build.build.build_number,
                    'build_version': stream_build.build_version,
                    'status': stream_build.status,
                    'timestamp': stream_build.build.timestamp.isoformat(),
                    'relative_timestamp': stream_build.build.relative_timestamp
                }
            print(json.dumps(status_data, indent=2))
        else:
            # Human-readable output
            print("Pipeline Status")
            print("=" * 50)
            for stream, stream_build in status.items():
                status_icon = "🟢" if stream_build.status == "green" else "🟡" if stream_build.status == "yellow" else "🔴"
                print(f"{status_icon} {stream}: Build #{stream_build.build.build_number} ({stream_build.build_version}) - {stream_build.build.relative_timestamp}")
                
    except Exception as e:
        print(f"Error fetching pipeline status: {e}")
        sys.exit(1)

def cmd_retry(args):
    """Retry a build."""
    jenkins_client = setup_jenkins_client()
    
    try:
        job_name, build_number = parse_jenkins_url(args.url)
        result = retry_jenkins_build(jenkins_client, job_name, build_number)
        print(result)
    except Exception as e:
        print(f"Error retrying build: {e}")
        sys.exit(1)

def cmd_rpms(args):
    """Get RPM packages for a build version."""
    try:
        if args.url:
            # Extract version from build URL
            jenkins_client = setup_jenkins_client()
            build = get_build_from_url(jenkins_client, args.url)
            if not build.build_version:
                print("Error: Could not extract build version from build")
                sys.exit(1)
            version = build.build_version
            architecture = args.arch
        else:
            version = args.version
            architecture = args.arch
            
        rpms = get_rpms_for_build(version, architecture)
        
        if args.json:
            print(json.dumps(rpms, indent=2))
        else:
            print(f"RPM packages for version {version} ({architecture or 'x86_64'}):")
            print("=" * 50)
            for pkg_name, pkg_version in sorted(rpms.items()):
                print(f"{pkg_name}: {pkg_version}")
                
    except Exception as e:
        print(f"Error fetching RPMs: {e}")
        sys.exit(1)

def run_cli(argv=None):
    """Run CLI with given arguments. If argv is None, uses sys.argv[1:]."""
    parser = argparse.ArgumentParser(
        description="CoreOS Pipeline Assistant - Standalone Jenkins Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s analyze https://jenkins.example.com/job/release/123/
  %(prog)s logs https://jenkins.example.com/job/release/123/
  %(prog)s info https://jenkins.example.com/job/release/123/
  %(prog)s builds https://jenkins.example.com/job/release/123/ --limit 10
  %(prog)s status --json
  %(prog)s retry https://jenkins.example.com/job/release/123/
  %(prog)s rpms --version 40.20240101.1.0 --arch x86_64
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze a build with LLM')
    analyze_parser.add_argument('url', help='Jenkins job URL')
    analyze_parser.add_argument('--logs', action='store_true', help='Force include logs in analysis')
    analyze_parser.set_defaults(func=cmd_analyze)
    
    # logs command
    logs_parser = subparsers.add_parser('logs', help='Get build logs')
    logs_parser.add_argument('url', help='Jenkins job URL')
    logs_parser.set_defaults(func=cmd_logs)
    
    # info command
    info_parser = subparsers.add_parser('info', help='Get build information')
    info_parser.add_argument('url', help='Jenkins job URL')
    info_parser.set_defaults(func=cmd_info)
    
    # builds command
    builds_parser = subparsers.add_parser('builds', help='List builds for a job')
    builds_parser.add_argument('url', help='Jenkins job URL (job name will be extracted)')
    builds_parser.add_argument('--limit', type=int, default=20, help='Limit number of builds shown (default: 20)')
    builds_parser.add_argument('--json', action='store_true', help='Output as JSON')
    builds_parser.set_defaults(func=cmd_builds)
    
    # status command
    status_parser = subparsers.add_parser('status', help='Get overall pipeline status')
    status_parser.add_argument('--json', action='store_true', help='Output as JSON')
    status_parser.set_defaults(func=cmd_status)
    
    # retry command
    retry_parser = subparsers.add_parser('retry', help='Retry a build')
    retry_parser.add_argument('url', help='Jenkins job URL')
    retry_parser.set_defaults(func=cmd_retry)
    
    # rpms command
    rpms_parser = subparsers.add_parser('rpms', help='Get RPM packages for a build')
    rpms_group = rpms_parser.add_mutually_exclusive_group(required=True)
    rpms_group.add_argument('--url', help='Jenkins job URL (extract version from build)')
    rpms_group.add_argument('--version', help='Build version (e.g., 40.20240101.1.0)')
    rpms_parser.add_argument('--arch', help='Architecture (default: x86_64)')
    rpms_parser.add_argument('--json', action='store_true', help='Output as JSON')
    rpms_parser.set_defaults(func=cmd_rpms)
    
    args = parser.parse_args(argv)
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)

def main():
    """Main entry point for CLI execution."""
    run_cli()

if __name__ == "__main__":
    main()