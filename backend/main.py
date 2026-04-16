from fastapi import FastAPI
from database import engine
import models

from routes import chat, customer, knowledge

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(chat.router, prefix="/chat")
app.include_router(customer.router, prefix="/customer")
app.include_router(knowledge.router, prefix="/knowledge")
