"""SQLAlchemy engine factory. Core + textual SQL only — no ORM."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from arestoteles.config import load_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(load_settings().database_url, pool_pre_ping=True)
