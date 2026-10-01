import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND)

# Los tests nunca deben usar una API key real ni el .env del usuario
os.environ["GROQ_API_KEY"] = ""
os.environ.pop("ADMIN_TOKEN", None)
os.environ.pop("FRONTEND_ALLOWED_ORIGINS", None)
