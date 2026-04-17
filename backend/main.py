from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from database import engine
import models

from routes import chat, customer, knowledge
from database import engine
from models import Base

Base.metadata.create_all(bind=engine)

models.Base.metadata.create_all(bind=engine)

app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all sites
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chat.router, prefix="/chat")
app.include_router(customer.router, prefix="/customer")
app.include_router(knowledge.router, prefix="/knowledge")
