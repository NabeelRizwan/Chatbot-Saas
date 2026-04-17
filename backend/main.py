from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

# ✅ IMPORT ROUTES
from routes import chat
from routes import upload
from routes import customer

# ✅ CREATE APP FIRST
app = FastAPI()

# ✅ ENABLE CORS (for widget usage)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ STATIC FILES (SAFE CHECK)
if os.path.exists("backend/static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ✅ INCLUDE ROUTES
app.include_router(chat.router, prefix="/chat")
app.include_router(upload.router, prefix="/knowledge")
app.include_router(customer.router, prefix="/customer")

# ✅ ROOT ENDPOINT
@app.get("/")
def root():
    return {"message": "API is running"}
