import pytest

from evalkit import client as client_module
from tests.stub_server import Stub


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture
def stub_url(stub):
    return stub.url


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(client_module, "RETRY_BASE_SECONDS", 0.0)
