"""initial schema: pgvector extension, all tables, HNSW index on chunks

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-19

"""

from collections.abc import Sequence

from alembic import op

from app.db import tables  # noqa: F401  — register ORM models
from app.db.base import Base

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable pgvector BEFORE creating any table that references Vector().
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create all ORM-declared tables in one shot.
    Base.metadata.create_all(bind=op.get_bind())

    # 3. HNSW index for fast cosine-similarity search over chunk embeddings.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
    Base.metadata.drop_all(bind=op.get_bind())
    op.execute("DROP EXTENSION IF EXISTS vector")
