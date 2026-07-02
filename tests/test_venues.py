"""Backend tests for Venues feature (Phase 2)"""
import pytest
import requests
import os

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def auth_token():
    """Login as test user and get token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "test@turf.ro", "password": "test123"})
    if resp.status_code == 401:
        # Register the user
        r = requests.post(f"{BASE_URL}/api/auth/signup", json={
            "email": "test@turf.ro", "password": "test123",
            "full_name": "Ion Popescu", "city": "București",
            "position": "midfielder", "level": "intermediate"
        })
        assert r.status_code == 200, f"Signup failed: {r.text}"
        return r.json()['token']
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()['token']

@pytest.fixture(scope="module")
def created_venue_id(auth_token):
    """Create a test venue and return its ID"""
    headers = {"Authorization": f"Bearer {auth_token}"}
    resp = requests.post(f"{BASE_URL}/api/venues", json={
        "name": "TEST_Teren Fotbal Central",
        "address": "Strada Principala 1",
        "city": "București",
        "surface_type": "artificial",
        "price_per_hour": 150.0,
        "working_hours": "08:00 - 22:00",
        "description": "Test venue for automated testing"
    }, headers=headers)
    # If already exists, get from list
    if resp.status_code == 400 and "already exists" in resp.text:
        list_resp = requests.get(f"{BASE_URL}/api/venues", params={"search": "TEST_Teren Fotbal Central"})
        venues = list_resp.json()
        return venues[0]['id'] if venues else None
    assert resp.status_code == 200, f"Create venue failed: {resp.text}"
    return resp.json()['id']

# GET /api/venues - empty or list
class TestGetVenues:
    def test_get_venues_returns_list(self):
        resp = requests.get(f"{BASE_URL}/api/venues")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        print(f"GET /api/venues: {len(data)} venues found")

    def test_get_venues_with_surface_filter(self):
        resp = requests.get(f"{BASE_URL}/api/venues", params={"surface_type": "artificial"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        for v in data:
            assert v['surface_type'] == 'artificial'
        print(f"Surface filter works: {len(data)} artificial venues")

    def test_get_venues_with_search(self):
        resp = requests.get(f"{BASE_URL}/api/venues", params={"search": "TEST_"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestCreateVenue:
    def test_create_venue_requires_auth(self):
        resp = requests.post(f"{BASE_URL}/api/venues", json={
            "name": "Unauthorized Venue", "address": "Test"
        })
        assert resp.status_code == 401

    def test_create_venue_success(self, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        import time
        unique_name = f"TEST_Venue_{int(time.time())}"
        resp = requests.post(f"{BASE_URL}/api/venues", json={
            "name": unique_name,
            "address": "Strada Test 99",
            "city": "București",
            "surface_type": "grass",
            "price_per_hour": 100.0,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data['name'] == unique_name
        assert data['surface_type'] == 'grass'
        assert 'id' in data
        print(f"Venue created: {data['id']}")

    def test_create_duplicate_venue_fails(self, auth_token, created_venue_id):
        """Creating a venue with same name+city should return 400"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.post(f"{BASE_URL}/api/venues", json={
            "name": "TEST_Teren Fotbal Central",
            "address": "Any Address",
            "city": "București",
        }, headers=headers)
        assert resp.status_code == 400


class TestGetVenueById:
    def test_get_venue_by_id(self, created_venue_id):
        resp = requests.get(f"{BASE_URL}/api/venues/{created_venue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data['id'] == created_venue_id
        assert 'reviews' in data
        assert 'avg_rating' in data
        assert 'review_count' in data
        print(f"Venue detail: {data['name']}, {data['review_count']} reviews")

    def test_get_venue_invalid_id(self):
        resp = requests.get(f"{BASE_URL}/api/venues/000000000000000000000000")
        assert resp.status_code == 404


class TestVenueReviews:
    def test_add_review_requires_auth(self, created_venue_id):
        resp = requests.post(f"{BASE_URL}/api/venues/{created_venue_id}/reviews", json={
            "venue_id": created_venue_id, "quality": 4, "surface": 3, "facilities": 4
        })
        assert resp.status_code == 401

    def test_add_review_success(self, auth_token, created_venue_id):
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.post(f"{BASE_URL}/api/venues/{created_venue_id}/reviews", json={
            "venue_id": created_venue_id,
            "quality": 4,
            "surface": 3,
            "facilities": 5,
            "comment": "Test review - automated"
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert 'message' in data
        print(f"Review result: {data['message']}")

    def test_review_persisted_in_venue(self, auth_token, created_venue_id):
        """After adding review, GET venue should show updated ratings"""
        resp = requests.get(f"{BASE_URL}/api/venues/{created_venue_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data['review_count'] >= 1
        assert data['avg_rating'] > 0
        print(f"Reviews after add: {data['review_count']}, avg: {data['avg_rating']}")

    def test_update_existing_review(self, auth_token, created_venue_id):
        """Adding review again (same user) should update it, not fail"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        resp = requests.post(f"{BASE_URL}/api/venues/{created_venue_id}/reviews", json={
            "venue_id": created_venue_id,
            "quality": 5,
            "surface": 5,
            "facilities": 5,
            "comment": "Updated review"
        }, headers=headers)
        assert resp.status_code == 200

