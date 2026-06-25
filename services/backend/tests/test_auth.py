import asyncio
import uuid


async def _register(client, email=None, password="password123"):
    email = email or f"{uuid.uuid4()}@e.com"
    return await client.post("/auth/register", json={"email": email, "password": password})


async def test_register_returns_token_and_sets_cookie(client):
    r = await _register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["email"]
    assert r.cookies.get("ac_refresh")  # refresh 下发到 httpOnly cookie


async def test_register_duplicate_email_409(client):
    email = f"{uuid.uuid4()}@e.com"
    await _register(client, email)
    r2 = await _register(client, email)
    assert r2.status_code == 409


async def test_register_short_password_422(client):
    r = await client.post("/auth/register", json={"email": "x@e.com", "password": "short"})
    assert r.status_code == 422


async def test_login_ok_and_wrong_password(client):
    email = f"{uuid.uuid4()}@e.com"
    await _register(client, email, "password123")
    ok = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = await client.post("/auth/login", json={"email": email, "password": "wrong"})
    assert bad.status_code == 401


async def test_login_unknown_email_401(client):
    r = await client.post(
        "/auth/login", json={"email": f"{uuid.uuid4()}@e.com", "password": "password123"}
    )
    assert r.status_code == 401


async def test_me_requires_token(client):
    r = await _register(client)
    access = r.json()["access_token"]
    assert (await client.get("/auth/me")).status_code == 401
    yes = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert yes.status_code == 200 and yes.json()["email"]


async def test_me_rejects_garbage_token(client):
    r = await client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


async def test_refresh_rotates_and_reuse_detected(client):
    reg = await _register(client)
    old = reg.cookies.get("ac_refresh")
    client.cookies.clear()  # 不让 jar 自动带,显式控制
    r1 = await client.post("/auth/refresh", cookies={"ac_refresh": old})
    assert r1.status_code == 200 and r1.json()["access_token"]
    new = r1.cookies.get("ac_refresh")
    assert new and new != old  # 轮换:发了新的
    client.cookies.clear()
    # 重用旧的(已吊销)→ 401 且触发吊销该用户全部
    r2 = await client.post("/auth/refresh", cookies={"ac_refresh": old})
    assert r2.status_code == 401
    client.cookies.clear()
    # 新的也被连带吊销 → 也 401
    r3 = await client.post("/auth/refresh", cookies={"ac_refresh": new})
    assert r3.status_code == 401


async def test_concurrent_refresh_no_double_spend(client):
    # I-1:同一 refresh 并发提交 → 恰一个成功(原子轮换),另一个判重用 401,无"双花"。
    reg = await _register(client)
    tok = reg.cookies.get("ac_refresh")
    client.cookies.clear()
    r1, r2 = await asyncio.gather(
        client.post("/auth/refresh", cookies={"ac_refresh": tok}),
        client.post("/auth/refresh", cookies={"ac_refresh": tok}),
    )
    assert sorted([r1.status_code, r2.status_code]) == [200, 401]


async def test_refresh_without_cookie_401(client):
    client.cookies.clear()
    assert (await client.post("/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh(client):
    reg = await _register(client)
    tok = reg.cookies.get("ac_refresh")
    out = await client.post("/auth/logout", cookies={"ac_refresh": tok})
    assert out.status_code == 204
    client.cookies.clear()
    assert (await client.post("/auth/refresh", cookies={"ac_refresh": tok})).status_code == 401


# ── 移动端:refresh token 走响应体(不依赖 cookie)──


async def test_register_returns_refresh_in_body(client):
    # 移动端:refresh 也在 body 返回(存 Keychain),且与 cookie 是同一个 token
    r = await _register(client)
    body = r.json()
    assert body["refresh_token"]
    assert body["refresh_token"] == r.cookies.get("ac_refresh")


async def test_refresh_via_body_rotates_and_reuse_detected(client):
    # 移动端无 cookie:refresh 放 body 发,照样轮换;旧的重用被检测
    reg = await _register(client)
    rt = reg.json()["refresh_token"]
    client.cookies.clear()  # 模拟移动端:无 cookie
    r1 = await client.post("/auth/refresh", json={"refresh_token": rt})
    assert r1.status_code == 200
    new_rt = r1.json()["refresh_token"]
    assert new_rt and new_rt != rt  # body 返回轮换后的新 refresh
    client.cookies.clear()
    assert (await client.post("/auth/refresh", json={"refresh_token": rt})).status_code == 401


async def test_refresh_empty_body_no_cookie_401(client):
    # 既无 cookie 也无 body refresh → 401(不崩)
    client.cookies.clear()
    assert (await client.post("/auth/refresh", json={})).status_code == 401


async def test_logout_via_body_revokes(client):
    # 移动端 logout:body 带 refresh,吊销之
    reg = await _register(client)
    rt = reg.json()["refresh_token"]
    client.cookies.clear()
    out = await client.post("/auth/logout", json={"refresh_token": rt})
    assert out.status_code == 204
    client.cookies.clear()
    assert (await client.post("/auth/refresh", json={"refresh_token": rt})).status_code == 401
