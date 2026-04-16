from sqlalchemy import Column, Integer, String, Text
from database import Base

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    api_key = Column(String, unique=True)

class Knowledge(Base):
    __tablename__ = "knowledge"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer)
    content = Column(Text)
