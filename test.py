import unittest
from unittest.mock import patch, Mock
import json
from datetime import datetime, timedelta
import requests # Import requests

# Mock external dependencies before importing modules that use them
with patch.dict('os.environ', {
    "SLACK_BOT_TOKEN": "mock_slack_bot_token",
    "SLACK_APP_TOKEN": "mock_slack_app_token",
    "GEMINI_API_KEY": "mock_gemini_api_key",
    "JENKINS_URL": "http://mock-jenkins.com",
    "JENKINS_TOKEN": "mock_jenkins_token"
}):
    with patch('google.genai.Client'), \
         patch('slack_bolt.App'):
        # Import modules after patching environment and other top-level imports
        from jenkins import Jenkins, JenkinsException
        from main import _human_friendly_time_diff, get_associated_jenkins_build, Build, get_jenkins_build_logs, get_list_of_builds_for_job, get_pipeline_status, StreamBuild


class TestUtils(unittest.TestCase):
    def setUp(self):
        self.jenkins_patcher = patch('main.jenkins_server')
        self.jenkins_mock = self.jenkins_patcher.start()
        self.jenkins_mock.reset_mock()

    def tearDown(self):
        self.jenkins_patcher.stop()

    def test_human_friendly_time_diff(self):
        now = datetime.now()
        self.assertEqual(_human_friendly_time_diff(now), "just now")
        self.assertEqual(_human_friendly_time_diff(now - timedelta(minutes=5)), "5 minutes ago")
        self.assertEqual(_human_friendly_time_diff(now - timedelta(hours=2)), "2 hours ago")
        self.assertEqual(_human_friendly_time_diff(now - timedelta(days=3)), "3 days ago")

    @patch('main.slack_app.client.conversations_history')
    def test_get_associated_jenkins_build_thread(self, mock_conversations_history):
        # Mock Slack API response for a thread
        mock_conversations_history.return_value = {
            "messages": [{
                "text": "Check this build: https://jenkins.example.com/job/my-job/123/",
                "ts": "12345.67890"
            }]
        }
        # Mock Jenkins API response
        self.jenkins_mock.get_build_info.return_value = {
            "number": 123,
            "description": "[my-stream] [x86_64 aarch64 ppc64le s390x] Build 1.0.0 (version-1.0)",
            "result": "SUCCESS",
            "timestamp": (datetime.now() - timedelta(hours=1)).timestamp() * 1000
        }

        build = get_associated_jenkins_build(channel="test_channel", thread_ts="12345.67890")
        self.assertEqual(build.job_name, "my-job")
        self.assertEqual(build.build_number, 123)
        self.assertEqual(build.build_result, "SUCCESS")
        self.assertIsNotNone(build.timestamp)
        self.assertIsNotNone(build.relative_timestamp)
        self.assertEqual(build.build_version, "1.0.0") # Extracted from the description
        self.assertEqual(build.architectures, ["x86_64", "aarch64", "ppc64le", "s390x"]) # Parsed architectures
        self.assertEqual(build.stream, "my-stream") # Parsed stream
        self.jenkins_mock.get_build_info.assert_called_once_with("my-job", 123)

    @patch('main.slack_app.client.conversations_history')
    def test_get_associated_jenkins_build_no_thread(self, mock_conversations_history):
        # Mock Slack API response for no thread (latest message)
        mock_conversations_history.return_value = {
            "messages": [{
                "text": "Build failed: https://jenkins.example.com/job/another-job/456/",
                "ts": "98765.43210"
            }]
        }
        # Mock Jenkins API response
        self.jenkins_mock.get_build_info.return_value = {
            "number": 456,
            "description": "Failed build",
            "result": "FAILURE",
            "timestamp": (datetime.now() - timedelta(days=2)).timestamp() * 1000
        }

        build = get_associated_jenkins_build(channel="test_channel")
        self.assertEqual(build.job_name, "another-job")
        self.assertEqual(build.build_number, 456)
        self.assertEqual(build.build_result, "FAILURE")
        self.assertIsNotNone(build.timestamp)
        self.assertIsNotNone(build.relative_timestamp)
        self.assertIsNone(build.build_version) # No version in description
        self.assertIsNone(build.architectures) # No architectures in description
        self.assertIsNone(build.stream) # No stream in description
        self.jenkins_mock.get_build_info.assert_called_once_with("another-job", 456)

    @patch('main.slack_app.client.conversations_history')
    def test_get_associated_jenkins_build_no_match(self, mock_conversations_history):
        mock_conversations_history.return_value = {
            "messages": [{
                "text": "Just a regular message without a Jenkins URL.",
                "ts": "11111.22222"
            }]
        }
        # Expecting a default Build object with job_name="", build_number=0
        build = get_associated_jenkins_build(channel="test_channel")
        self.assertEqual(build.job_name, "")
        self.assertEqual(build.build_number, 0)
        self.assertIsNone(build.build_result)
        self.assertIsNone(build.architectures)
        self.assertIsNone(build.stream)
        self.jenkins_mock.get_build_info.assert_not_called() # Should not call get_build_info if no match

    def test_get_jenkins_build_logs_success(self):
        self.jenkins_mock.get_build_console_output.return_value = "Mocked console output"
        logs = get_jenkins_build_logs("test_job", 123)
        self.assertEqual(logs, "Mocked console output")
        self.jenkins_mock.get_build_console_output.assert_called_once_with("test_job", 123)

    def test_get_jenkins_build_logs_error(self):
        self.jenkins_mock.get_build_console_output.side_effect = JenkinsException("Log fetch error")
        logs = get_jenkins_build_logs("non_existent_job", 123)
        self.assertIn("Error fetching Jenkins logs", logs)

    def test_get_list_of_builds_for_job_success(self):
        self.jenkins_mock.get_job_info.return_value = {
            "builds": [
                {"number": 1, "description": "[streamA] [aarch64 x86_64 s390x ppc64le] Build 1.0 (version-1.0)", "result": "SUCCESS", "timestamp": (datetime.now() - timedelta(days=1)).timestamp() * 1000},
                {"number": 2, "description": "[streamB] [x86_64] Build 1.1", "result": "FAILURE", "timestamp": (datetime.now() - timedelta(hours=5)).timestamp() * 1000}
            ]
        }
        builds = get_list_of_builds_for_job("test_job")
        self.assertEqual(len(builds), 2)
        self.assertEqual(builds[0].build_number, 1)
        self.assertEqual(builds[0].architectures, ["aarch64", "x86_64", "s390x", "ppc64le"])
        self.assertEqual(builds[0].stream, "streamA")
        self.assertEqual(builds[0].build_version, "1.0")
        self.assertEqual(builds[1].build_number, 2)
        self.assertEqual(builds[1].build_result, "FAILURE")
        self.assertEqual(builds[1].architectures, ["x86_64"])
        self.assertEqual(builds[1].stream, "streamB")
        self.assertEqual(builds[1].build_version, "1.1")
        self.jenkins_mock.get_job_info.assert_called_once_with("test_job", depth=1)

    def test_get_list_of_builds_for_job_error(self):
        self.jenkins_mock.get_job_info.side_effect = JenkinsException("Job info error")
        builds = get_list_of_builds_for_job("non_existent_job")
        self.assertEqual(len(builds), 0)

    @patch('main.get_list_of_builds_for_job')
    def test_get_pipeline_status(self, mock_get_list_of_builds_for_job):
        # Mock current time for consistent testing of time-based status
        mock_now = datetime(2025, 6, 7, 12, 0, 0) # Example fixed time
        with patch('main.datetime') as mock_dt:
            mock_dt.now.return_value = mock_now
            mock_dt.fromtimestamp = datetime.fromtimestamp # Ensure this is not mocked
            mock_dt.timedelta = timedelta # Ensure this is not mocked

            mock_get_list_of_builds_for_job.return_value = [
                Build(job_name="release", build_number=3, build_description="[streamA] [aarch64 x86_64 s390x ppc64le] Build 1.1 (version-1.1)", build_result="SUCCESS", timestamp=mock_now - timedelta(hours=12), relative_timestamp="", build_version="1.1", architectures=["aarch64", "x86_64", "s390x", "ppc64le"], stream="streamA"), # GREEN (most recent for A)
                Build(job_name="release", build_number=1, build_description="[streamA] [aarch64 x86_64 s390x ppc64le] Build 1.0 (version-1.0)", build_result="SUCCESS", timestamp=mock_now - timedelta(hours=24), relative_timestamp="", build_version="1.0", architectures=["aarch64", "x86_64", "s390x", "ppc64le"], stream="streamA"), # Older GREEN for A
                Build(job_name="release", build_number=2, build_description="[streamB] [aarch64 x86_64 s390x ppc64le] Build 2.0 (version-2.0)", build_result="SUCCESS", timestamp=mock_now - timedelta(hours=48), relative_timestamp="", build_version="2.0", architectures=["aarch64", "x86_64", "s390x", "ppc64le"], stream="streamB"), # YELLOW
                Build(job_name="release", build_number=5, build_description="[streamD] [aarch64 x86_64 s390x ppc64le] Build 4.0 (version-4.0)", build_result="SUCCESS", timestamp=mock_now - timedelta(hours=96), relative_timestamp="", build_version="4.0", architectures=["aarch64", "x86_64", "s390x", "ppc64le"], stream="streamD"), # RED
                Build(job_name="release", build_number=4, build_description="[streamC] Build 3.0", build_result=None, timestamp=mock_now - timedelta(hours=5), relative_timestamp="", build_version="3.0", architectures=None, stream="streamC"),  # Skipped (None result)
            ]

            status = get_pipeline_status()

            self.assertIn("streamA", status)
            self.assertEqual(status["streamA"].build.build_number, 3)
            self.assertEqual(status["streamA"].build_version, "1.1")
            self.assertEqual(status["streamA"].build.build_result, "SUCCESS") # Check stream status
            self.assertEqual(status["streamA"].status.value, "green") # Check StreamStatus status

            self.assertEqual(status["streamA"].build.architectures, ["aarch64", "x86_64", "s390x", "ppc64le"])
            self.assertEqual(status["streamA"].build.stream, "streamA")

            self.assertIn("streamB", status)
            self.assertEqual(status["streamB"].build.build_number, 2)
            self.assertEqual(status["streamB"].build_version, "2.0")
            self.assertEqual(status["streamB"].build.build_result, "SUCCESS") # Check stream status
            self.assertEqual(status["streamB"].status.value, "yellow") # Check StreamStatus status

            self.assertEqual(status["streamB"].build.architectures, ["aarch64", "x86_64", "s390x", "ppc64le"])
            self.assertEqual(status["streamB"].build.stream, "streamB")

            self.assertNotIn("streamC", status)

            self.assertIn("streamD", status)
            self.assertEqual(status["streamD"].build.build_number, 5)
            self.assertEqual(status["streamD"].build_version, "4.0")
            self.assertEqual(status["streamD"].build.build_result, "SUCCESS") # Check stream status
            self.assertEqual(status["streamD"].status.value, "red") # Check StreamStatus status

            self.assertEqual(status["streamD"].build.architectures, ["aarch64", "x86_64", "s390x", "ppc64le"])
            self.assertEqual(status["streamD"].build.stream, "streamD")


if __name__ == '__main__':
    unittest.main()
