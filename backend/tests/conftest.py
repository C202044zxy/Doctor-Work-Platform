import pytest


@pytest.fixture(autouse=True)
def isolated_secrets(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-only-jwt-secret-32-characters-long")
    monkeypatch.setenv("PATIENT_DATA_KEY", "test-only-patient-data-key")
