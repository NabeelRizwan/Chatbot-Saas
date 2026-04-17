import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Get DATABASE URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

# 🚨 Fail fast if not set (VERY IMPORTANT)
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Check Render environment variables.")

# Create engine (PostgreSQL - Supabase)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

# Session
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class
Base = declarative_base()

# Dependency (for FastAPI routes)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
