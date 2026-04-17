from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ✅ IMPORT ROUTES
from routes import chat
from routes import upload

# ✅ CREATE APP FIRST (VERY IMPORTANT)
app = FastAPI()

# ✅ ENABLE CORS (for your widget)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ OPTIONAL: STATIC FILES (ONLY if folder exists)
# If you created backend/static → keep this
# Otherwise comment this line
# app.mount("/static", StaticFiles(directory="backend/static"), name="static")

# ✅ ADD ROUTES (AFTER app is created)
app.include_router(chat.router, prefix="/chat")
app.include_router(upload.router, prefix="/knowledge")

# ✅ ROOT CHECK (optional but useful)
@app.get("/")
def root():
    return {"message": "API is running"}
