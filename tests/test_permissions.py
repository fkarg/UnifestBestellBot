import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot.filters import IsDeveloper, IsOrga
from unifestbestellbot.models import Registration

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


async def test_is_orga_accepts_orga_member(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    assert await IsOrga()(fake_message(user_id=1), db_session=s, config=config)


async def test_is_orga_rejects_non_orga(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    assert not await IsOrga()(fake_message(user_id=1), db_session=s, config=config)


async def test_is_orga_rejects_unregistered(s, config):
    assert not await IsOrga()(fake_message(user_id=1), db_session=s, config=config)


async def test_is_developer_accepts_matching_chat_id(s, config):
    # conftest.py sets DEVELOPER_CHAT_ID=100
    assert await IsDeveloper()(fake_message(user_id=100))


async def test_is_developer_rejects_others(s, config):
    assert not await IsDeveloper()(fake_message(user_id=99))
