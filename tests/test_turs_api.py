"""
Backend API tests for Turf app
Tests: auth, matches, notifications, stats, profile
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '').rstrip('/')

TEST_USER = {"email": "test@turf.ro", "password": "test123"}
TEST_USER2 = {"email": "andrei@turf.ro", "password": "test123"}

@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=TEST_USER)
    if resp.status_code != 200:
        pytest.skip("Login failed, skipping auth-dependent tests")
    return resp.json()["token"]

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


class TestAuth:
    """Authentication endpoints"""

    def test_login_success(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json=TEST_USER)
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == TEST_USER["email"]

    def test_login_wrong_password(self):
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": TEST_USER["email"], "password": "wrongpass"})
        assert resp.status_code == 401

    def test_me_endpoint(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert "hashed_password" not in data

    def test_signup_duplicate_email(self, auth_headers):
        resp = requests.post(f"{BASE_URL}/api/auth/signup", json={
            "email": TEST_USER["email"],
            "password": "test123",
            "full_name": "Test",
            "city": "București"
        })
        assert resp.status_code == 400


class TestMatches:
    """Matches endpoints"""

    def test_get_matches(self):
        resp = requests.get(f"{BASE_URL}/api/matches")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_matches_response_structure(self):
        resp = requests.get(f"{BASE_URL}/api/matches")
        assert resp.status_code == 200
        data = resp.json()
        if data:
            match = data[0]
            assert "id" in match
            assert "_id" not in match
            assert "title" in match
            assert "status" in match

    def test_create_match(self, auth_headers):
        from datetime import datetime, timezone, timedelta
        scheduled = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        resp = requests.post(f"{BASE_URL}/api/matches", headers=auth_headers, json={
            "title": "TEST_Match Backend",
            "location_name": "Stadion Test",
            "location_lat": 44.4268,
            "location_lng": 26.1025,
            "scheduled_at": scheduled,
            "players_needed": 10,
            "format": "5v5",
            "level": "intermediate",
            "cost_per_player": 0,
            "description": "Test match"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["title"] == "TEST_Match Backend"
        return data["id"]

    def test_get_match_by_id(self, auth_headers):
        # First create a match, then get it
        from datetime import datetime, timezone, timedelta
        scheduled = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        create_resp = requests.post(f"{BASE_URL}/api/matches", headers=auth_headers, json={
            "title": "TEST_Get Match",
            "location_name": "Test",
            "location_lat": 44.4268,
            "location_lng": 26.1025,
            "scheduled_at": scheduled,
            "players_needed": 10,
            "format": "5v5",
            "level": "beginner",
            "cost_per_player": 0
        })
        assert create_resp.status_code == 200
        match_id = create_resp.json()["id"]

        get_resp = requests.get(f"{BASE_URL}/api/matches/{match_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == match_id

    def test_get_match_players(self, auth_headers):
        from datetime import datetime, timezone, timedelta
        scheduled = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        create_resp = requests.post(f"{BASE_URL}/api/matches", headers=auth_headers, json={
            "title": "TEST_Players Match",
            "location_name": "Test",
            "location_lat": 44.4268,
            "location_lng": 26.1025,
            "scheduled_at": scheduled,
            "players_needed": 10,
            "format": "5v5",
            "level": "beginner",
            "cost_per_player": 0
        })
        match_id = create_resp.json()["id"]
        players_resp = requests.get(f"{BASE_URL}/api/matches/{match_id}/players")
        assert players_resp.status_code == 200
        players = players_resp.json()
        assert isinstance(players, list)
        assert len(players) >= 1  # organizer is auto-added

    def test_my_matches(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/my-matches", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestNotifications:
    """Notifications endpoints"""

    def test_get_notifications(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/notifications", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_unread_count(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/notifications/unread-count", headers=auth_headers)
        assert resp.status_code == 200
        assert "count" in resp.json()

    def test_mark_all_read(self, auth_headers):
        resp = requests.put(f"{BASE_URL}/api/notifications/read-all", headers=auth_headers)
        assert resp.status_code == 200


class TestStats:
    """Stats endpoints"""

    def test_get_my_stats(self, auth_headers):
        resp = requests.get(f"{BASE_URL}/api/stats/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "matches_played" in data
        assert "goals" in data
        assert "assists" in data
        assert "avg_rating" in data


class TestProfile:
    """Profile endpoints"""

    def test_get_profile(self, auth_headers):
        me_resp = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        user_id = me_resp.json()["id"]
        resp = requests.get(f"{BASE_URL}/api/profile/{user_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "match_history" in data
        assert "hashed_password" not in data

    def test_update_profile(self, auth_headers):
        resp = requests.put(f"{BASE_URL}/api/auth/profile", headers=auth_headers, json={
            "city": "București"
        })
        assert resp.status_code == 200
        assert "hashed_password" not in resp.json()


