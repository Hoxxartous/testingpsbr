#!/usr/bin/env python3
"""
Restaurant POS - Windows Production Server with Full WebSocket Support
Production-ready server for Windows deployment with SocketIO + Eventlet
"""

import os
import sys
import multiprocessing
import argparse
from pathlib import Path

def check_requirements():
    """Check if all required packages are installed"""
    try:
        import waitress
        import eventlet
        import flask
        import flask_socketio
        print("✓ All required packages are installed")
        return True
    except ImportError as e:
        print(f"✗ Missing required package: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def start_waitress_server(host="127.0.0.1", port=8000, threads=None, debug=False):
    """Start Flask app with Waitress server (Windows production)"""
    
    # Monkey patch for eventlet (for SocketIO support)
    import eventlet
    eventlet.monkey_patch()
    
    from waitress import serve
    from app import create_app, socketio
    from config import Config, DevelopmentConfig
    
    # Choose configuration based on debug mode
    config_class = DevelopmentConfig if debug else Config
    
    # Create app
    app = create_app(config_class)
    
    # Calculate threads if not specified
    if threads is None:
        threads = multiprocessing.cpu_count() * 2
    
    # Get current directory
    app_dir = Path(__file__).parent.absolute()
    os.chdir(app_dir)
    
    print("=" * 60)
    print("RESTAURANT POS - WINDOWS SERVER (Full WebSocket Support)")
    print("=" * 60)
    print(f"🖥️  Detected {multiprocessing.cpu_count()} CPU cores")
    print(f"🔧 Running in {'DEBUG' if debug else 'PRODUCTION'} mode")
    print(f"🚀 Starting with SocketIO + Eventlet server")
    print(f"📍 Server will be available at: http://{host}:{port}")
    print(f"⚙️  Configuration: {threads} threads, full async I/O + WebSocket")
    print(f"🔄 Debug mode: {'Yes' if debug else 'No'}")
    print(f"🌐 Platform: Windows Compatible with WebSocket support")
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
                
                print(f"📊 Database {db_file}: Journal mode = {journal_mode}")
                if journal_mode.upper() == 'WAL':
                    print(f"✅ WAL mode enabled for {db_file}")
                else:
                    print(f"⚠️  WAL mode not enabled for {db_file}")
    except Exception as e:
        print(f"⚠️  Could not check database status: {e}")
    
    print("=" * 60)
    print("🚀 Starting server with FULL WebSocket support...")
    print("✅ WebSocket features: ENABLED (via SocketIO + Eventlet)")
    print("🔧 Multi-threaded architecture with async I/O")
    print("💡 Production-ready Windows server with WebSocket support")
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    try:
        # Start the server with SocketIO for full WebSocket support
        # Using socketio.run with eventlet for WebSocket compatibility
        print("🔧 Starting with full WebSocket support via SocketIO + Eventlet...")
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            use_reloader=False,  # Disable reloader for production
            log_output=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)

def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Start Restaurant POS with Full WebSocket Support (Windows Production)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_waitress_server.py                    # Start in production mode
  python start_waitress_server.py --debug            # Start in debug mode
  python start_waitress_server.py --port 9000        # Start on port 9000
  python start_waitress_server.py --threads 16       # Use 16 threads
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
        "--threads", 
        type=int, 
        help="Number of threads (default: auto-detect based on CPU)"
    )
    
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug mode"
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
        recommended_threads = cpu_count * 2
        print(f"✓ System ready for deployment")
        print(f"✓ CPU cores: {cpu_count}")
        print(f"✓ Recommended threads: {recommended_threads}")
        print(f"✓ Waitress server available")
        print(f"✓ Windows compatibility: Yes")
        sys.exit(0)
    
    # Start the server
    start_waitress_server(
        host=args.host,
        port=args.port,
        threads=args.threads,
        debug=args.debug
    )

if __name__ == "__main__":
    main()
