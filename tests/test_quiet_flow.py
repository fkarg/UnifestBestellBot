from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import register as register_flow
from unifestbestellbot.models import Registration, now_utc

from .fakes import fake_message


@pytest.fixture
def s():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# --- /quiet ---------------------------------------------------------------


async def test_quiet_default_30_minutes(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/quiet")
    before = now_utc()
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    after = now_utc()

    reg = repo.registration_for(s, 1)
    assert reg.mute_peer_until is not None
    delta = reg.mute_peer_until - before
    assert timedelta(minutes=29) <= delta <= timedelta(minutes=31)
    assert "30" in msg.answer.call_args.args[0]
    assert after - before < timedelta(seconds=5)  # sanity


async def test_quiet_custom_duration(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/quiet 120")
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    reg = repo.registration_for(s, 1)
    delta = reg.mute_peer_until - now_utc()
    assert timedelta(minutes=118) <= delta <= timedelta(minutes=121)


async def test_quiet_rejects_zero(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/quiet 0")
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    reg = repo.registration_for(s, 1)
    assert reg.mute_peer_until is None
    assert "Benutzung" in msg.answer.call_args.args[0]


async def test_quiet_rejects_above_maximum(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/quiet 9999")
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1).mute_peer_until is None


async def test_quiet_rejects_non_numeric(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/quiet abc")
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1).mute_peer_until is None


async def test_quiet_requires_registration(s, config):
    msg = fake_message(user_id=1, text="/quiet")
    await register_flow.cmd_quiet(msg, db_session=s, config=config)
    assert "/register" in msg.answer.call_args.args[0]


# --- /loud ----------------------------------------------------------------


async def test_loud_clears_active_mute(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    future = now_utc() + timedelta(minutes=30)
    repo.set_mute(s, 1, until=future)
    msg = fake_message(user_id=1, text="/loud")
    await register_flow.cmd_loud(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1).mute_peer_until is None
    assert "🔔" in msg.answer.call_args.args[0]


async def test_loud_is_idempotent_when_already_loud(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar 1"))
    msg = fake_message(user_id=1, text="/loud")
    await register_flow.cmd_loud(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "nicht ausgeschaltet" in body


async def test_loud_requires_registration(s, config):
    msg = fake_message(user_id=1, text="/loud")
    await register_flow.cmd_loud(msg, db_session=s, config=config)
    assert "/register" in msg.answer.call_args.args[0]


# --- group_members exclude_muted -----------------------------------------


def test_group_members_excludes_muted_when_requested(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="BiMi"))
    repo.upsert_registration(s, Registration(chat_id=2, group_name="BiMi"))
    repo.upsert_registration(s, Registration(chat_id=3, group_name="BiMi"))
    repo.set_mute(s, 2, until=now_utc() + timedelta(minutes=30))

    # Peer mode skips muted member 2.
    assert set(repo.group_members(s, "BiMi", exclude_muted=True)) == {1, 3}
    # Broadcast mode includes everyone.
    assert set(repo.group_members(s, "BiMi", exclude_muted=False)) == {1, 2, 3}


def test_group_members_treats_expired_mute_as_unmuted(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="BiMi"))
    repo.set_mute(s, 1, until=now_utc() - timedelta(minutes=1))

    assert repo.group_members(s, "BiMi", exclude_muted=True) == [1]
