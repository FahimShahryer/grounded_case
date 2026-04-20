from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    document_id: int
    chunk_index: int
    text: str
    line_start: int | None
    line_end: int | None
    section_header: str | None
    doc_type: str
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime
