#!/usr/bin/env python3
"""
Restaurant POS - Windows-Compatible Eventlet Server
Provides Gunicorn-like functionality with eventlet on Windows
"""

import os
import sys
import multiprocessing
import argparse
from pathlib import Path

def check_requirements():
    """Check if all required packages are installed"""
    try:
        import eventlet
        import flask
        import flask_socketio
        print("[OK] All required packages are installed")
        return True
    except ImportError as e:
        print(f"[ERROR] Missing required package: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def start_eventlet_server(host="127.0.0.1", port=8000, debug=False, workers=1):
    """Start Flask app with eventlet server (Windows compatible)"""
    
    # Monkey patch for eventlet
    import eventlet
    eventlet.monkey_patch()
    
    from app import create_app, socketio
    from config import Config, DevelopmentConfig
    
    # Choose configuration based on debug mode
    config_class = DevelopmentConfig if debug else Config
    
    # Create app
    app = create_app(config_class)
    
    # Get current directory
    app_dir = Path(__file__).parent.absolute()
    os.chdir(app_dir)
    
    print("=" * 60)
    print("RESTAURANT POS - EVENTLET SERVER (Windows Compatible)")
    print("=" * 60)
    print(f"[CPU] Detected {multiprocessing.cpu_count()} CPU cores")
    print(f"[MODE] Running in {'DEBUG' if debug else 'PRODUCTION'} mode")
    print(f"[SERVER] Starting with Eventlet server")
    print(f"[URL] Server will be available at: http://{host}:{port}")
    print(f"[CONFIG] Configuration: Single process, eventlet async I/O")
    print(f"[DEBUG] Debug mode: {'Yes' if debug else 'No'}")
    print(f"[RELOAD] Auto-reload: {'Yes' if debug else 'No'}")
    print("=" * 60)
    
    # Check database health
    try:
        import sqlite3
        
        db_files = ['restaurant_pos.db', 'restaurant_pos_dev.db']
        for db_file in db_files:
            if os.path.exists(db_file):
                conn = sqlite3.connect(db_file)
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0]
                conn.close()
                
                print(f"[DB] Database {db_file}: Journal mode = {journal_mode}")
                if journal_mode.upper() == 'WAL':
                    print(f"[OK] WAL mode enabled for {db_file}")
                else:
                    print(f"[WARN] WAL mode not enabled for {db_file}")
    except Exception as e:
        print(f"[WARN] Could not check database status: {e}")
    
    print("=" * 60)
    
    try:
        # Start the server with eventlet
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            use_reloader=debug,  # Auto-reload in debug mode
            log_output=True
        )
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down server...")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] Failed to start server: {e}")
        sys.exit(1)

def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Start Restaurant POS with Eventlet (Windows Compatible)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_eventlet_server.py                    # Start in production mode
  python start_eventlet_server.py --debug            # Start in debug mode
  python start_eventlet_server.py --port 9000        # Start on port 9000
  python start_eventlet_server.py --debug --port 5000 # Debug mode on port 5000
        """
    )
    
    parser.add_argument(
        "--host", 
        default="127.0.0.1", 
        help="Host to bind to (default: 127.0.0.1)"
    )
    
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="Port to bind to (default: 8000)"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug mode with auto-reload"
    )
    
    parser.add_argument(
        "--check", 
        action="store_true", 
        help="Check requirements and exit"
    )
    
    args = parser.parse_args()
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    if args.check:
        cpu_count = multiprocessing.cpu_count()
        recommended_workers = cpu_count * 2 + 1
        print(f"[OK] System ready for deployment")
        print(f"[OK] CPU cores: {cpu_count}")
        print(f"[OK] Recommended workers: {recommended_workers}")
        print(f"[OK] Eventlet server available")
        print(f"[OK] Windows compatibility: Yes")
        sys.exit(0)
    
    # Start the server
    start_eventlet_server(
        host=args.host,
        port=args.port,
        debug=args.debug
    )

if __name__ == "__main__":
    main()
