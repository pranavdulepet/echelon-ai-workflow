"""
Vercel serverless function handler for FastAPI app.
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Set database path relative to project root for serverless
if "SQLITE_PATH" not in os.environ:
    project_root = Path(__file__).parent.parent
    db_path = project_root / "data" / "forms.sqlite"
    os.environ["SQLITE_PATH"] = str(db_path)

from mangum import Mangum
from backend.app.main import app

# Wrap FastAPI app with Mangum for AWS Lambda/Vercel compatibility
handler = Mangum(app, lifespan="off")

