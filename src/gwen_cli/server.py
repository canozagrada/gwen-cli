"""GWEN Server - FastAPI backend entry point."""
import sys
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_path))


def main():
    """Run the GWEN FastAPI server."""
    import uvicorn
    from backend.main import app
    
    print("Starting GWEN Backend Server...")
    print("Backend API: http://127.0.0.1:8000")
    print("Press Ctrl+C to stop")
    
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
