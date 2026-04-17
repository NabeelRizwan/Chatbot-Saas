from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Customer, Knowledge

import PyPDF2
import docx

router = APIRouter()

def extract_text(file: UploadFile):
    filename = file.filename.lower()

    if filename.endswith(".txt"):
        return file.file.read().decode("utf-8")

    elif filename.endswith(".pdf"):
        reader = PyPDF2.PdfReader(file.file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text

    elif filename.endswith(".docx"):
        doc = docx.Document(file.file)
        return "\n".join([p.text for p in doc.paragraphs])

    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")


@router.post("/upload")
def upload_file(
    api_key: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 🔑 Validate customer
    customer = db.query(Customer).filter(Customer.api_key == api_key).first()
    if not customer:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 📄 Extract text
    text = extract_text(file)

    # ✂️ Split into chunks (important)
    chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]

    # 💾 Store in DB
    for chunk in chunks:
        db.add(Knowledge(content=chunk, customer_id=customer.id))

    db.commit()

    return {"message": f"{len(chunks)} chunks added"}
