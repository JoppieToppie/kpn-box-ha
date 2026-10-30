from pathlib import Path
import sys

import pytest
import pytest_socket

import custom_components

# The harness ships its own testing_config/custom_components package; make ours visible too
custom_components.__path__.append(str(Path(__file__).parents[1] / "custom_components"))

if sys.platform == "win32":
    # Windows' asyncio loop needs an AF_INET socketpair; HTTP is still mocked by aioclient_mock
    pytest_socket.disable_socket = lambda *a, **k: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
