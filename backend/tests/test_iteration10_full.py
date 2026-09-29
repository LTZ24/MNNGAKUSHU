"""Iteration 10: Full end-to-end backend regression + bug hunt.

Focus areas per the review request:
 - Auth flows (register/login/me/refresh/logout/forgot/change/lockout)
 - Admin CRUD + publish toggle + reset + pad-quiz + pad-jukugo + pad-all polling
 - Public chapters + filtering, quiz endpoints (bunpo/kanji/kotoba/susun/campuran)
 - Library attempts idempotency, weak items, due-cards, SM-2 review
 - Route/permission guards (learner cannot access admin, unauth for progress)
 - Security bugs to look for:
     * forgot-password leaking temporary_password in response body
     * user enumeration via forgot-password 404 vs 200
"""
import os
import time
import uuid
import requests
import pytest

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
ADMIN_EMAIL = "mpdigitech.id@gmail.com"
ADMIN_PASSWORD = "Admin@2026"


# ------------------- fixtures -------------------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    yield s


@pytest.fixture(scope="module")
def learner_session():
    s = requests.Session()
    email = f"test_iter10_{uuid.uuid4().hex[:8]}@ex.com"
    pw = "LearnerPass1!"
    r = s.post(f"{BASE}/auth/register", json={"email": email, "password": pw, "name": "Iter10"})
    assert r.status_code == 200, r.text
    s._email = email
    s._password = pw
    yield s


# ------------------- Auth -------------------
class TestAuth:
    def test_register_login_me_flow(self):
        s = requests.Session()
        email = f"test_iter10_flow_{uuid.uuid4().hex[:6]}@ex.com"
        r = s.post(f"{BASE}/auth/register", json={"email": email, "password": "Abcdefg1!"})
        assert r.status_code == 200
        assert r.json()["email"] == email
        assert r.json()["role"] == "learner"

        me = s.get(f"{BASE}/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == email

        # refresh
        rf = s.post(f"{BASE}/auth/refresh")
        assert rf.status_code == 200

        # logout
        lo = s.post(f"{BASE}/auth/logout")
        assert lo.status_code == 200

        # me should now 401
        me2 = s.get(f"{BASE}/auth/me")
        assert me2.status_code == 401

        # login again
        li = s.post(f"{BASE}/auth/login", json={"email": email, "password": "Abcdefg1!"})
        assert li.status_code == 200

    def test_login_wrong_password_returns_401(self):
        s = requests.Session()
        email = f"test_iter10_wp_{uuid.uuid4().hex[:6]}@ex.com"
        s.post(f"{BASE}/auth/register", json={"email": email, "password": "Abcdefg1!"})
        r = s.post(f"{BASE}/auth/login", json={"email": email, "password": "WrongPass99!"})
        assert r.status_code == 401

    def test_password_lt_8_returns_422(self):
        r = requests.post(f"{BASE}/auth/login", json={"email": "x@y.z", "password": "short"})
        assert r.status_code == 422

    def test_brute_force_lockout_429(self):
        """5 wrong password attempts >=8 chars from same IP+email should lock (429)."""
        s = requests.Session()
        email = f"test_iter10_lock_{uuid.uuid4().hex[:6]}@ex.com"
        s.post(f"{BASE}/auth/register", json={"email": email, "password": "GoodPass1!"})
        codes = []
        for _ in range(5):
            r = s.post(f"{BASE}/auth/login", json={"email": email, "password": "WrongPass9!"})
            codes.append(r.status_code)
        # 6th attempt (even correct password) should now be 429
        r6 = s.post(f"{BASE}/auth/login", json={"email": email, "password": "GoodPass1!"})
        assert r6.status_code == 429, f"expected 429 after 5 fails; got codes={codes}, then {r6.status_code}"

    def test_forgot_password_no_leak_generic_message(self):
        """Post-fix: forgot-password returns only generic message, no temp password."""
        s = requests.Session()
        email = f"test_iter10_fp_{uuid.uuid4().hex[:6]}@ex.com"
        s.post(f"{BASE}/auth/register", json={"email": email, "password": "OrigPass1!"})
        r = requests.post(f"{BASE}/auth/forgot-password", json={"email": email})
        assert r.status_code == 200
        assert "temporary_password" not in r.json()

    def test_forgot_password_unknown_generic_200(self):
        r = requests.post(f"{BASE}/auth/forgot-password",
                          json={"email": f"nobody_{uuid.uuid4().hex[:6]}@x.z"})
        assert r.status_code == 200

    def test_forgot_password_admin_no_takeover(self):
        r = requests.post(f"{BASE}/auth/forgot-password", json={"email": ADMIN_EMAIL})
        assert r.status_code == 200
        assert "temporary_password" not in r.json()
        # Admin login must still work
        li = requests.post(f"{BASE}/auth/login",
                           json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert li.status_code == 200

    def test_change_password_with_wrong_current(self, learner_session):
        r = learner_session.post(f"{BASE}/auth/change-password",
                                 json={"current_password": "WrongOld1!", "new_password": "NewPass1!"})
        assert r.status_code == 400


# ------------------- Public Chapters -------------------
class TestPublic:
    def test_chapters_list_and_counts(self):
        r = requests.get(f"{BASE}/chapters")
        assert r.status_code == 200
        chs = r.json()
        assert len(chs) >= 49
        assert all("number" in c and "book" in c for c in chs)
        # book 1 covers 2..25, book 2 covers 26..50 per PRD
        nums = sorted(c["number"] for c in chs)
        assert 1 in nums or 2 in nums
        assert 50 in nums

    def test_chapter_detail_hides_answers(self):
        r = requests.get(f"{BASE}/chapters/1")
        assert r.status_code == 200
        c = r.json()["content"]
        for q in c.get("quiz_bunpo", []):
            assert "answer_index" not in q, "answer leaked in public chapter detail"
        for q in c.get("quiz_susun", []):
            assert "correct_order" not in q

    def test_chapter_not_found(self):
        r = requests.get(f"{BASE}/chapters/999")
        assert r.status_code == 404


# ------------------- Library Quiz -------------------
class TestLibrary:
    @pytest.mark.parametrize("qtype", ["bunpo", "kanji", "kotoba", "susun"])
    def test_library_quiz_types(self, qtype):
        r = requests.get(f"{BASE}/library/quiz", params={"type": qtype, "book": 1, "limit": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == qtype
        assert isinstance(body["questions"], list)
        # No answer leak in bunpo (must not have answer_index)
        if qtype == "bunpo":
            for q in body["questions"]:
                assert "answer_index" not in q
        if qtype == "susun":
            for q in body["questions"]:
                assert "tokens" in q and "correct_length" in q

    def test_library_quiz_campuran_count(self):
        r = requests.get(f"{BASE}/library/quiz", params={"type": "campuran", "book": 1, "limit": 15})
        assert r.status_code == 200
        qs = r.json()["questions"]
        # Should be up to 15 (5 kanji + 5 kotoba + 5 bunpo)
        assert 5 <= len(qs) <= 15
        kinds = {q["kind"] for q in qs}
        # Mix of at least 2 kinds expected
        assert len(kinds) >= 2, f"campuran not mixed: {kinds}"

    def test_library_quiz_invalid_type(self):
        r = requests.get(f"{BASE}/library/quiz", params={"type": "invalid"})
        assert r.status_code == 400

    def test_library_kanji_kotoba_shape(self):
        r = requests.get(f"{BASE}/library/kanji", params={"book": 1})
        assert r.status_code == 200
        b = r.json()
        assert "cards" in b and "total" in b
        r2 = requests.get(f"{BASE}/library/kotoba", params={"book": 1})
        assert r2.status_code == 200
        assert "cards" in r2.json()

    def test_attempt_idempotent(self, learner_session):
        op_id = str(uuid.uuid4())
        payload = {"type": "kanji", "book": 1,
                   "items": [{"id": "kanji|1|私", "picked": "saya"}],
                   "operation_id": op_id}
        r1 = learner_session.post(f"{BASE}/library/quiz/attempt", json=payload)
        r2 = learner_session.post(f"{BASE}/library/quiz/attempt", json=payload)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"], "operation_id idempotency broken"

    def test_weak_items_endpoint(self, learner_session):
        r = learner_session.get(f"{BASE}/library/weak-items")
        assert r.status_code == 200
        assert "cards" in r.json()

    def test_review_and_due_cards(self, learner_session):
        # Post a review, quality=5 -> due in future
        r = learner_session.post(f"{BASE}/library/review",
                                 json={"card_id": "kanji|1|私", "quality": 5})
        assert r.status_code == 200
        # Due list
        d = learner_session.get(f"{BASE}/library/due-cards")
        assert d.status_code == 200

    def test_due_cards_requires_auth(self):
        r = requests.get(f"{BASE}/library/due-cards")
        assert r.status_code == 401


# ------------------- Progress -------------------
class TestProgress:
    def test_progress_requires_auth(self):
        r = requests.get(f"{BASE}/progress")
        assert r.status_code == 401

    def test_progress_fields(self, learner_session):
        r = learner_session.get(f"{BASE}/progress")
        assert r.status_code == 200
        b = r.json()
        for k in ("completed", "total_chapters", "streak", "best_score", "average_score",
                  "total_sessions", "progress", "attempts"):
            assert k in b, f"missing progress field {k}"
        # PRD requires total_chapters=50
        assert b["total_chapters"] == 50, f"expected 50 chapters got {b['total_chapters']}"


# ------------------- Admin authz -------------------
class TestAdminAuthz:
    def test_learner_forbidden_admin(self, learner_session):
        r = learner_session.get(f"{BASE}/admin/chapters")
        assert r.status_code == 403

    def test_unauth_forbidden_admin(self):
        r = requests.get(f"{BASE}/admin/chapters")
        assert r.status_code == 401

    def test_admin_can_list_chapters(self, admin_session):
        r = admin_session.get(f"{BASE}/admin/chapters")
        assert r.status_code == 200
        assert len(r.json()) >= 49


# ------------------- Admin CRUD & publish -------------------
class TestAdminCRUD:
    def test_admin_get_edit_reset_chapter(self, admin_session):
        # Get chapter 3 (avoid touching 1/2 that may be under pad-quiz)
        n = 3
        g = admin_session.get(f"{BASE}/admin/chapters/{n}")
        assert g.status_code == 200
        original_title = g.json()["title"]

        # PUT: change title
        new_title = f"TEST_TITLE_{uuid.uuid4().hex[:6]}"
        try:
            p = admin_session.put(f"{BASE}/admin/chapters/{n}", json={"title": new_title})
            assert p.status_code == 200
            assert p.json()["title"] == new_title
            # Verify GET reflects it
            g2 = admin_session.get(f"{BASE}/admin/chapters/{n}")
            assert g2.json()["title"] == new_title
        finally:
            # Restore
            admin_session.post(f"{BASE}/admin/chapters/{n}/reset")

    def test_publish_toggle(self, admin_session):
        n = 4
        # Toggle off
        r1 = admin_session.post(f"{BASE}/admin/chapters/{n}/publish")
        assert r1.status_code == 200
        state = r1.json()["published"]
        # If unpublished, public list should NOT contain it
        if state is False:
            pub = requests.get(f"{BASE}/chapters/{n}")
            assert pub.status_code == 404
        # Toggle back
        r2 = admin_session.post(f"{BASE}/admin/chapters/{n}/publish")
        assert r2.status_code == 200
        assert r2.json()["published"] != state

    def test_reset_chapter(self, admin_session):
        n = 5
        r = admin_session.post(f"{BASE}/admin/chapters/{n}/reset")
        assert r.status_code == 200
        assert r.json()["quiz_padded"] is False


# ------------------- Pad quiz / jukugo / pad-all -------------------
class TestPadding:
    def test_pad_all_polling(self, admin_session):
        r = admin_session.post(f"{BASE}/admin/pad-all-quizzes")
        assert r.status_code == 200
        b = r.json()
        assert "job_id" in b and "total" in b
        # Poll a couple times (don't block long, LLM may be slow)
        job_id = b["job_id"]
        for _ in range(3):
            time.sleep(1)
            js = admin_session.get(f"{BASE}/admin/pad-jobs/{job_id}")
            assert js.status_code == 200
            if js.json().get("finished"):
                break

    def test_pad_jobs_404(self, admin_session):
        r = admin_session.get(f"{BASE}/admin/pad-jobs/does-not-exist")
        assert r.status_code == 404
