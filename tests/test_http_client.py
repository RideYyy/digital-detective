import unittest

import requests

from digital_detective.http_client import HttpClient, RetryPolicy


def response(status, retry_after=None):
    item = requests.Response()
    item.status_code = status
    item.url = "https://api.example.test/data"
    item._content = b"{}"
    if retry_after is not None:
        item.headers["Retry-After"] = retry_after
    return item


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)

    def get(self, *args, **kwargs):
        return self.responses.pop(0)


class HttpClientTests(unittest.TestCase):
    def test_429_honors_retry_after(self):
        waits = []
        client = HttpClient(
            "test-agent",
            policy=RetryPolicy(attempts=2, min_interval=0),
            session=FakeSession([response(429, "3"), response(200)]),
            sleep=waits.append,
        )
        self.assertEqual(client.get("https://api.example.test/data").status_code, 200)
        self.assertEqual(waits, [3.0])


if __name__ == "__main__":
    unittest.main()
