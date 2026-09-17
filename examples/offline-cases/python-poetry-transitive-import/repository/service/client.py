import requests


def health_check(base_url: str) -> int:
    return requests.get(f"{base_url}/health", timeout=5).status_code
