import pytest


@pytest.fixture
def tmp_state(tmp_path):
    """Provides a temporary state directory for Memory/ArtifactStore tests."""
    return tmp_path


@pytest.fixture
def tmp_sandbox(tmp_path):
    """Provides a temporary sandbox directory for MCP file tool tests."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    return sandbox
