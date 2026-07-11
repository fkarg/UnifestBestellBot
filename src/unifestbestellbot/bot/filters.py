"""Custom filters for permission gating. They participate in route
selection rather than running as runtime guards inside handlers."""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from sqlmodel import Session

from .. import repo
from ..config import AppConfig
from ..settings import get_settings


class IsOrga(BaseFilter):
    async def __call__(
        self,
        event: Message | CallbackQuery,
        db_session: Session,
        config: AppConfig,
    ) -> bool:
        if event.from_user is None:
            return False
        reg = repo.registration_for(db_session, event.from_user.id)
        return reg is not None and config.is_orga(reg.group_name)


class IsDeveloper(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if event.from_user is None:
            return False
        return event.from_user.id == get_settings().developer_chat_id


class IsOrgaOrDeveloper(BaseFilter):
    """Permit the normal orga command path plus the developer escape hatch."""

    async def __call__(
        self,
        event: Message | CallbackQuery,
        db_session: Session,
        config: AppConfig,
    ) -> bool:
        if event.from_user is None:
            return False
        if event.from_user.id == get_settings().developer_chat_id:
            return True
        reg = repo.registration_for(db_session, event.from_user.id)
        return reg is not None and config.is_orga(reg.group_name)
