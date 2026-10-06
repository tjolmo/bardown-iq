from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import os

class Base(DeclarativeBase):
    pass

# SQL statement logging is opt-in (SQL_ECHO=1); echo=True logged every statement, including multi-thousand-row inserts
SQL_ECHO = os.getenv("SQL_ECHO", "").lower() in ("1", "true", "yes")

engine = create_async_engine(os.getenv("DATABASE_URL"), echo=SQL_ECHO)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)