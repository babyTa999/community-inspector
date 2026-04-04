#!/usr/bin/env python3
"""Run IceWhale CRM web server."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from crm.web import app


def main():
    parser = argparse.ArgumentParser(description="IceWhale CRM Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    print(f"Starting IceWhale CRM server at http://{args.host}:{args.port}")
    uvicorn.run(
        "crm.web:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
