import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from database import create_user, get_db


def get_csrf(client, url="/login"):
    response = client.get(url)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    if match:
        return match.group(1).decode()
    return None


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "campuscare-test.db"
    application = create_app(database_path=str(db_path))
    application.config["TESTING"] = True
    with application.test_client() as test_client:
        yield test_client


def register_student(client, username="student1", email="student1@example.com", password="password123"):
    token = get_csrf(client, "/register")
    return client.post(
        "/register",
        data={
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
            "csrf_token": token,
        },
        follow_redirects=True,
    )


def login(client, username, password):
    token = get_csrf(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def create_admin(client):
    db_path = client.application.config["DATABASE_PATH"]
    create_user(db_path, "admin1", "admin1@example.com", generate_password_hash("adminpass123"), "admin")
    return "admin1", "adminpass123"


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "healthy", "application": "CampusCare"}


def test_unauthenticated_redirect(client):
    for path in ["/", "/complaints", "/complaints/new", "/admin"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (302, 303)
        assert "/login" in response.headers.get("Location", "")


def test_student_registration(client):
    response = register_student(client)
    assert response.status_code == 200
    assert b"Registration successful" in response.data


def test_duplicate_registration_rejected(client):
    register_student(client)
    response = register_student(client)
    assert response.status_code == 200
    assert b"already" in response.data.lower()


def test_login_success_and_failure(client):
    register_student(client)
    response = login(client, "student1", "password123")
    assert response.status_code == 200
    assert b"Welcome back" in response.data

    token = get_csrf(client, "/")
    client.post("/logout", data={"csrf_token": token}, follow_redirects=True)

    bad = login(client, "student1", "wrongpassword")
    assert b"Invalid username or password" in bad.data


def test_logout(client):
    register_student(client)
    login(client, "student1", "password123")
    token = get_csrf(client, "/")
    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=True)
    assert response.status_code == 200
    assert b"logged out" in response.data.lower()


def test_student_cannot_access_admin(client):
    register_student(client)
    login(client, "student1", "password123")
    response = client.get("/admin", follow_redirects=True)
    assert response.status_code == 403


def test_csrf_protection(client):
    response = client.post("/login", data={"username": "x", "password": "y"}, follow_redirects=True)
    assert response.status_code == 400



def test_student_complaint_submission_and_isolation(client):
    register_student(client, "studentA", "a@example.com", "password123")
    login(client, "studentA", "password123")

    token = get_csrf(client, "/complaints/new")
    response = client.post(
        "/complaints/new",
        data={
            "category": "IT / Network",
            "title": "Wi-Fi not working",
            "description": "Internet is down in lab 2.",
            "priority": "High",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"submitted successfully" in response.data
    assert b"Wi-Fi not working" in client.get("/complaints").data

    client.post("/logout", data={"csrf_token": get_csrf(client, "/")}, follow_redirects=True)
    register_student(client, "studentB", "b@example.com", "password123")
    login(client, "studentB", "password123")
    list_response = client.get("/complaints")
    assert b"Wi-Fi not working" not in list_response.data

    detail = client.get("/complaints/CC-0001", follow_redirects=True)
    assert detail.status_code == 403


def test_student_cannot_change_status(client):
    register_student(client)
    login(client, "student1", "password123")
    token = get_csrf(client, "/complaints/new")
    client.post(
        "/complaints/new",
        data={
            "category": "Classroom",
            "title": "Broken chair",
            "description": "Chair is broken.",
            "priority": "Low",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    csrf = get_csrf(client, "/")
    response = client.post(
        "/admin/complaints/1/status",
        data={"status": "Resolved", "csrf_token": csrf},
        follow_redirects=True,
    )
    assert response.status_code == 403


def test_admin_view_all_and_update_status(client):
    register_student(client)
    login(client, "student1", "password123")
    token = get_csrf(client, "/complaints/new")
    client.post(
        "/complaints/new",
        data={
            "category": "Classroom",
            "title": "Broken chair",
            "description": "Chair is broken.",
            "priority": "Low",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    client.post("/logout", data={"csrf_token": get_csrf(client, "/")}, follow_redirects=True)

    username, password = create_admin(client)
    login(client, username, password)

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Broken chair" in response.data

    csrf = get_csrf(client, "/admin")
    db_path = client.application.config["DATABASE_PATH"]
    conn = get_db(db_path)
    pk = conn.execute("SELECT id FROM complaints WHERE title='Broken chair'").fetchone()["id"]
    conn.close()

    update = client.post(
        f"/admin/complaints/{pk}/status",
        data={"status": "In Progress", "csrf_token": csrf},
        follow_redirects=True,
    )
    assert update.status_code == 200
    assert b"updated" in update.data.lower()

    csrf = get_csrf(client, "/admin")
    invalid = client.post(
        f"/admin/complaints/{pk}/status",
        data={"status": "Hacked", "csrf_token": csrf},
        follow_redirects=True,
    )
    assert invalid.status_code == 200
    assert b"Invalid status" in invalid.data


def test_dashboard_response(client):
    register_student(client)
    login(client, "student1", "password123")
    response = client.get("/")
    assert response.status_code == 200
    assert b"Campus overview" in response.data
    assert b"Total Complaints" in response.data
