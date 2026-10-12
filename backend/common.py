import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
DB = Path(os.getenv('DB_PATH', str(BASE / 'data' / 'scans.db')))
if not DB.is_absolute():
    DB = BASE / DB

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()

class Scan(BaseModel):
    id: UUID
    barcode: str = Field(min_length=1, max_length=512)

    @field_validator('barcode')
    @classmethod
    def validate_barcode(cls, value):
        if not value.strip():
            raise ValueError('條碼不能只有空白')
        return value
