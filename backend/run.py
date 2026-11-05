"""Entry point: python run.py"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("PAPERLENS_RELOAD", "0") == "1"
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)
