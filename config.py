import os
import firebase_admin # type: ignore
from firebase_admin import credentials, firestore # type: ignore

# ================= GEMINI CONFIG =================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("GEMINI_API_KEY not set — Gemini disabled")

# ================= FIREBASE CONFIG =================
if not firebase_admin._apps:
    cred = credentials.Certificate("truecheck-e1f3b-firebase-adminsdk-fbsvc-fdbd50bdc4.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()