import os

import pytest

from app import create_app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "campuscare-test.db"
    application = create_app(database_path=str(db_path))
    application.config["TESTING"] = True
    with application.test_client() as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"status": "healthy", "application": "CampusCare"}


def test_dashboard_response(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Campus overview" in response.data
    assert b"Total Complaints" in response.data


def test_submit_complaint_success(client):
    response = client.post(
        "/complaints/new",
        data={
            "category": "IT / Network",
            "title": "Wi-Fi not working",
            "description": "Internet is down in lab 2.",
            "priority": "High",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"submitted successfully" in response.data

    list_response = client.get("/complaints")
    assert list_response.status_code == 200
    assert b"Wi-Fi not working" in list_response.data
    assert b"CC-" in list_response.data


def test_submit_complaint_validation(client):
    response = client.post(
        "/complaints/new",
        data={"category": "", "title": "", "description": "", "priority": "High"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"required" in response.data.lower() or b"valid" in response.data.lower()
