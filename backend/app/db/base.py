from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM tables.

    Alembic reads `Base.metadata` when autogenerating migrations, so every
    ORM module must be importable from `app.db.tables`.
    """

    pass
