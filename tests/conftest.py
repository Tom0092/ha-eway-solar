"""Shared fixtures: load custom_components/ like a real installation would."""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
