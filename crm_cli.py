#!/usr/bin/env python3
"""CLI entry point for IceWhale CRM."""
from __future__ import annotations

import argparse
import sys


def serve_command(args):
    """Run the web server."""
    import uvicorn
    from crm.web import app

    print(f"Starting IceWhale CRM server at http://{args.host}:{args.port}")
    print(f"Database: crm.db")
    print(f"Uploads: crm/static/uploads/")
    print()
    print("Press Ctrl+C to stop")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def init_command(args):
    """Initialize database."""
    from crm.database import get_engine, init_db

    engine = get_engine()
    init_db(engine)
    print("Database initialized successfully at crm.db")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="IceWhale CRM - Community Signal & User Management System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python crm_cli.py serve              # Start server on default port 8080
  python crm_cli.py serve -p 3000      # Start server on port 3000
  python crm_cli.py init               # Initialize database only
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Run web server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    serve_parser.add_argument("-p", "--port", type=int, default=8080, help="Port to bind")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    serve_parser.set_defaults(func=serve_command)

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize database")
    init_parser.set_defaults(func=init_command)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
