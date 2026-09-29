"""Iteration 11: Verify security fixes + new admin reset endpoint + streak tz + quiz_susun shape."""
import os
import uuid
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN_EMAIL = "mpdigitech.id@gmail.com"
ADMIN_PASSWORD = "Admin@2026"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    yield s


@pytest.fixture()
def fresh_learner():
    s = requests.Session()
    email = f"test_iter11_{uuid.uuid4().hex[:8]}@ex.com"
    pw = "LearnerPass1!"
    r = s.post(f"{BASE}/auth/register", json={"email": email, "password": pw, "name": "Iter11"})
    assert r.status_code == 200, r.text
    s._email = email
    s._password = pw
    return s


# -------- SECURITY FIX: forgot-password ---------
class TestForgotPasswordFix:
    def test_forgot_password_returns_only_generic_message(self, fresh_learner):
        email = fresh_learner._email
        r = requests.post(f"{BASE}/auth/forgot-password", json={"email": email})
        assert r.status_code == 200
        b = r.json()
        assert "temporary_password" not in b, f"LEAK: {b}"
        assert "message" in b

    def test_forgot_password_unknown_email_generic_200(self):
        r = requests.post(f"{BASE}/auth/forgot-password",
                          json={"email": f"nobody_{uuid.uuid4().hex[:6]}@x.z"})
        assert r.status_code == 200
        assert "temporary_password" not in r.json()

    def test_forgot_password_does_not_change_password(self, fresh_learner):
        # Old password must still work after forgot-password
        email, pw = fresh_learner._email, fresh_learner._password
        requests.post(f"{BASE}/auth/forgot-password", json={"email": email})
        s2 = requests.Session()
        r = s2.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, "forgot-password must NOT change password"

    def test_admin_login_still_works(self):
        r = requests.post(f"{BASE}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200


# -------- NEW: admin reset password ---------
class TestAdminResetPassword:
    def test_anon_401(self):
        r = requests.post(f"{BASE}/admin/users/reset-password",
                          json={"email": "x@y.z"})
        assert r.status_code == 401

    def test_learner_403(self, fresh_learner):
        r = fresh_learner.post(f"{BASE}/admin/users/reset-password",
                               json={"email": "x@y.z"})
        assert r.status_code == 403

    def test_admin_unknown_email_404(self, admin_session):
        r = admin_session.post(f"{BASE}/admin/users/reset-password",
                               json={"email": f"nobody_{uuid.uuid4().hex[:6]}@x.z"})
        assert r.status_code == 404

    def test_admin_reset_full_flow(self, admin_session, fresh_learner):
        email = fresh_learner._email
        r = admin_session.post(f"{BASE}/admin/users/reset-password", json={"email": email})
        assert r.status_code == 200
        b = r.json()
        assert "temporary_password" in b and b["temporary_password"]
        temp = b["temporary_password"]
        # Old password should no longer work; sessions deleted
        # Try old password
        s_old = requests.Session()
        r_old = s_old.post(f"{BASE}/auth/login",
                           json={"email": email, "password": fresh_learner._password})
        assert r_old.status_code == 401
        # Login with temp
        s_new = requests.Session()
        r_new = s_new.post(f"{BASE}/auth/login", json={"email": email, "password": temp})
        assert r_new.status_code == 200
        me = s_new.get(f"{BASE}/auth/me")
        assert me.status_code == 200
        assert me.json().get("must_change_password") is True
        # change password
        cp = s_new.post(f"{BASE}/auth/change-password",
                        json={"current_password": temp, "new_password": "NewLearn1!"})
        assert cp.status_code == 200
        # login with new password
        s2 = requests.Session()
        r2 = s2.post(f"{BASE}/auth/login", json={"email": email, "password": "NewLearn1!"})
        assert r2.status_code == 200


# -------- Logout without session ---------
class TestLogoutNoSession:
    def test_logout_anon_200(self):
        s = requests.Session()
        r = s.post(f"{BASE}/auth/logout")
        assert r.status_code == 200

    def test_logout_deletes_session(self, fresh_learner):
        r = fresh_learner.post(f"{BASE}/auth/logout")
        assert r.status_code == 200
        me = fresh_learner.get(f"{BASE}/auth/me")
        assert me.status_code == 401


# -------- Lockout regression ---------
class TestLockout:
    def test_brute_force_429(self):
        s = requests.Session()
        email = f"test_iter11_lock_{uuid.uuid4().hex[:6]}@ex.com"
        s.post(f"{BASE}/auth/register", json={"email": email, "password": "GoodPass1!"})
        for _ in range(5):
            s.post(f"{BASE}/auth/login", json={"email": email, "password": "WrongPass9!"})
        r6 = s.post(f"{BASE}/auth/login", json={"email": email, "password": "GoodPass1!"})
        assert r6.status_code == 429


# -------- Progress streak with X-Timezone ---------
class TestProgressTimezone:
    def test_progress_default_tz(self, fresh_learner):
        r = fresh_learner.get(f"{BASE}/progress")
        assert r.status_code == 200
        assert "streak" in r.json()

    def test_progress_valid_tz(self, fresh_learner):
        r = fresh_learner.get(f"{BASE}/progress", headers={"X-Timezone": "Asia/Tokyo"})
        assert r.status_code == 200

    def test_progress_invalid_tz_no_500(self, fresh_learner):
        r = fresh_learner.get(f"{BASE}/progress", headers={"X-Timezone": "Not/AZone"})
        assert r.status_code == 200, r.text


# -------- quiz_susun shape ---------
class TestQuizSusunShape:
    def test_chapter_detail_susun_shape(self):
        r = requests.get(f"{BASE}/chapters/1")
        assert r.status_code == 200
        content = r.json()["content"]
        susuns = content.get("quiz_susun", [])
        if not susuns:
            pytest.skip("no quiz_susun in chapter 1")
        for q in susuns:
            assert "tokens" in q and isinstance(q["tokens"], list)
            assert "correct_length" in q
            assert q["correct_length"] > 0
            assert "correct_order" not in q


# -------- Cleanup lockouts at end ---------
def test_zzz_cleanup_lockouts():
    """Clear login_attempts to prevent lingering lockouts."""
    import subprocess
    subprocess.run(
        ["mongosh", "test_database", "--eval", "db.login_attempts.deleteMany({})"],
        capture_output=True, timeout=15,
    )
