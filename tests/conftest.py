import pytest
from tests import stub_server


@pytest.fixture
def stub_url():
    url, stop = stub_server.start()
    yield url
    stop()
