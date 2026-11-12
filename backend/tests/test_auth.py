import uuid


def test_register_with_email_and_login(client):
    email = f"ali-{uuid.uuid4().hex[:6]}@example.com"
    s, d = client.post("/api/auth/register", {"name": "Ali Raza", "email": email, "password": "secret123"})
    assert s == 201 and d["user"]["role"] == "passenger" and d["token"]
    s, d = client.post("/api/auth/login", {"identifier": email.upper(), "password": "secret123"})
    assert s == 200
    s, me = client.get("/api/me", token=d["token"])
    assert s == 200 and me["email"] == email


def test_register_with_phone_normalises_number(client):
    phone_tail = str(uuid.uuid4().int)[:9]
    s, d = client.post("/api/auth/register", {"name": "Sana", "phone": f"+923{phone_tail}", "password": "pass1234"})
    assert s == 201 and d["user"]["phone"] == f"03{phone_tail}"
    s, _ = client.post("/api/auth/login", {"identifier": f"03{phone_tail}", "password": "pass1234"})
    assert s == 200


def test_register_validation(client):
    s, d = client.post("/api/auth/register", {"name": "X Y", "email": "bad", "password": "short"})
    assert s == 422 and d["error"]["code"] == "validation_error"
    s, d = client.post("/api/auth/register", {"name": "No Contact", "password": "abc12345"})
    assert s == 422
    s, d = client.post("/api/auth/register", {"name": "Letters", "email": "a@b.co", "password": "onlyletters"})
    assert s == 422


def test_duplicate_email_rejected(client):
    s, d = client.post("/api/auth/register", {"name": "Dup", "email": "passenger@speedo.demo", "password": "abc12345"})
    assert s == 409 and d["error"]["code"] == "email_taken"


def test_wrong_password_and_unknown_user(client):
    s, d = client.post("/api/auth/login", {"identifier": "passenger@speedo.demo", "password": "nope-nope1"})
    assert s == 401 and d["error"]["code"] == "invalid_credentials"
    s, _ = client.post("/api/auth/login", {"identifier": "nobody@example.com", "password": "nope-nope1"})
    assert s == 401


def test_logout_revokes_token(client):
    tok = client.login("passenger@speedo.demo")
    assert client.get("/api/me", token=tok)[0] == 200
    assert client.post("/api/auth/logout", token=tok)[0] == 200
    s, d = client.get("/api/me", token=tok)
    assert s == 401 and d["error"]["code"] == "invalid_token"


def test_protected_endpoints_need_auth(client):
    assert client.get("/api/me", token="")[0] == 401
    assert client.get("/api/me", token="garbage.token.value")[0] == 401


def test_passwords_are_hashed(server):
    from app.db import get_db
    row = get_db().one("SELECT password_hash FROM users WHERE email = ?", ("passenger@speedo.demo",))
    assert row["password_hash"].startswith("scrypt$") and "Demo@12345" not in row["password_hash"]


def test_login_rate_limited(client):
    from app.security import rate_limiter
    from app.http import api
    spec = next(s for s in api.specs if s.path == "/api/auth/login")
    old = spec.rate
    spec.rate = 3
    rate_limiter.reset()
    try:
        codes = [client.post("/api/auth/login", {"identifier": "x@y.zz", "password": "abc12345"})[0] for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3] == 429
    finally:
        spec.rate = old
        rate_limiter.reset()
