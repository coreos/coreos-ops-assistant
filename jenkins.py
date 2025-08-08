import requests
import json
import functools
from typing import Optional, Dict


class JenkinsException(Exception):
    """Custom exception for Jenkins API errors."""
    pass


class Jenkins:
    def __init__(self, url: str, token: str, verify_ssl: bool = True):
        self.url = url.rstrip('/')
        self.headers = {"Authorization": f"Bearer {token}"}
        self.verify_ssl = verify_ssl

    def _get_json(self, path: str, params: Optional[Dict] = None) -> Dict:
        """Helper to make a GET request and return JSON."""
        full_url = f"{self.url}/{path}/api/json"
        try:
            response = requests.get(full_url, headers=self.headers, params=params, verify=self.verify_ssl)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.json()
        except requests.exceptions.RequestException as e:
            raise JenkinsException(f"Error fetching JSON from {full_url}: {e}")
        except json.JSONDecodeError as e:
            raise JenkinsException(f"Error decoding JSON from {full_url}: {e}")

    def _get_text(self, path: str) -> str:
        """Helper to make a GET request and return text."""
        full_url = f"{self.url}/{path}"
        try:
            response = requests.get(full_url, headers=self.headers, verify=self.verify_ssl)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            raise JenkinsException(f"Error fetching text from {full_url}: {e}")

    def _post_request(self, path: str, data: Optional[Dict] = None) -> requests.Response:
        """Helper to make a POST request."""
        full_url = f"{self.url}/{path}"
        try:
            response = requests.post(full_url, headers=self.headers, data=data, verify=self.verify_ssl)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise JenkinsException(f"Error performing POST request to {full_url}: {e}")

    @functools.lru_cache()
    def get_build_info(self, job_name: str, build_number: int) -> Dict:
        """Gets information about a specific build."""
        path = f"job/{job_name}/{build_number}"
        return self._get_json(path)

    @functools.lru_cache()
    def get_build_console_output(self, job_name: str, build_number: int) -> str:
        """Gets the console output for a specific build."""
        path = f"job/{job_name}/{build_number}/logText/progressiveText"
        return self._get_text(path)

    @functools.lru_cache()
    def get_job_info(self, job_name: str, depth: int = 0) -> Dict:
        """Gets information about a specific job."""
        path = f"job/{job_name}"
        params = {'depth': depth} if depth else None
        return self._get_json(path, params=params)

    def retry_build(self, job_name: str, build_number: int) -> str:
        """Retries a specific Jenkins build."""
        # Jenkins usually uses /replay or /retry for build retries
        # The /rebuild endpoint might be more appropriate for a direct retry
        path = f"job/{job_name}/{build_number}/retry"
        try:
            response = self._post_request(path)
            if response.status_code == 200:
                return f"Successfully initiated retry for {job_name} #{build_number}"
            else:
                return f"Failed to retry {job_name} #{build_number}. Status code: {response.status_code}, Response: {response.text}"
        except JenkinsException as e:
            return f"Error retrying build {job_name} #{build_number}: {e}"
