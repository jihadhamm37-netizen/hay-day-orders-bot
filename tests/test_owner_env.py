"""OWNER_USERNAME / OWNER_PASSWORD: create the owner, or reset a forgotten password and unlock the account."""
from app.main import ensure_owner
from app.services import admins


async def test_owner_created_then_reset(core, monkeypatch):
    monkeypatch.setenv("OWNER_USERNAME", "Jehad")
    monkeypatch.setenv("OWNER_PASSWORD", "qwert1QWERT")
    await ensure_owner(core)
    a = await admins.check_login(core, "Jehad", "qwert1QWERT", None)
    assert a["username"] == "jehad" and a["role"] == "owner"
    await core.pool.execute("UPDATE admins SET locked_until=now()+interval '1 hour', role='support' WHERE username='jehad'")
    monkeypatch.setenv("OWNER_PASSWORD", "NewPass12345")
    await ensure_owner(core)
    a = await admins.check_login(core, "jehad", "NewPass12345", None)
    assert a["role"] == "owner"
    await ensure_owner(core)                                   # unchanged → nothing happens
