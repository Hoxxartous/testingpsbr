#!/usr/bin/env python3
"""
Restaurant POS - Gunicorn Startup Script
Automatically starts the application with optimal Gunicorn + Eventlet configuration
"""

import os
import sys
import subprocess
import multiprocessing
from pathlib import Path

def get_cpu_info():
    """Get CPU information for worker calculation"""
    cpu_count = multiprocessing.cpu_count()
    recommended_workers = cpu_count * 2 + 1
    return cpu_count, recommended_workers

def check_requirements():
    """Check if all required packages are installed"""
    try:
        import platform
        
        # Check if running on Windows
        if platform.system() == 'Windows':
            print("⚠️  WARNING: Gunicorn does not support Windows natively")
            print("🔧 For Windows development, use: python start_eventlet_server.py")
            print("🔧 For Windows production, consider using: waitress or Docker")
            print()
        
        import gunicorn
        import eventlet
        import flask
        import flask_socketio
        print("✓ All required packages are installed")
        return True
    except ImportError as e:
        print(f"✗ Missing required package: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def start_gunicorn(host="0.0.0.0", port=8000, workers=None, reload=False, daemon=False):
    """Start Gunicorn with eventlet worker"""
    
    # Get current directory
    app_dir = Path(__file__).parent.absolute()
    os.chdir(app_dir)
    
    # Calculate workers if not specified
    if workers is None:
        cpu_count, workers = get_cpu_info()
        print(f"🖥️  Detected {cpu_count} CPU cores")
        print(f"🔧 Using {workers} workers (recommended: 2 * CPU + 1)")
    
    # Build Gunicorn command
    cmd = [
        "gunicorn",
        "-c", "gunicorn.conf.py",  # Use our configuration file
        "-b", f"{host}:{port}",    # Bind address
        "-w", str(workers),        # Number of workers
        "-k", "eventlet",          # Worker class
        "wsgi:application"         # WSGI application
    ]
    
    # Add optional flags
    if reload:
        cmd.append("--reload")
    
    if daemon:
        cmd.append("--daemon")
    
    print(f"🚀 Starting Restaurant POS with Gunicorn + Eventlet")
    print(f"📍 Server will be available at: http://{host}:{port}")
    print(f"⚙️  Configuration: {workers} workers, eventlet async I/O")
    print(f"🔄 Reload on changes: {'Yes' if reload else 'No'}")
    print(f"🌐 Daemon mode: {'Yes' if daemon else 'No'}")
    print(f"📝 Command: {' '.join(cmd)}")
    print("-" * 60)
    
    try:
        # Start Gunicorn
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start Gunicorn: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        sys.exit(0)

def main():
    """Main function with command line argument parsing"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Start Restaurant POS with Gunicorn + Eventlet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_gunicorn.py                    # Start with default settings
  python start_gunicorn.py --port 9000       # Start on port 9000
  python start_gunicorn.py --workers 4       # Use 4 workers
  python start_gunicorn.py --reload          # Enable auto-reload
  python start_gunicorn.py --daemon          # Run as daemon
        """
    )
    
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind to (default: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="Port to bind to (default: 8000)"
    )
    
    parser.add_argument(
        "--workers", 
        type=int, 
        help="Number of workers (default: auto-detect based on CPU)"
    )
    
    parser.add_argument(
        "--reload", 
        action="store_true", 
        help="Enable auto-reload on code changes"
    )
    
    parser.add_argument(
        "--daemon", 
        action="store_true", 
        help="Run as daemon process"
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
        cpu_count, recommended_workers = get_cpu_info()
        print(f"✓ System ready for deployment")
        print(f"✓ CPU cores: {cpu_count}")
        print(f"✓ Recommended workers: {recommended_workers}")
        sys.exit(0)
    
    # Start the server
    start_gunicorn(
        host=args.host,
        port=args.port,
        workers=args.workers,
        reload=args.reload,
        daemon=args.daemon
    )

if __name__ == "__main__":
    main()
