from app import create_app
import os

def main():
    """Create and return the Flask app with automatic initialization"""
    # Create app with default configuration
    # The app will automatically initialize the database on startup
    app = create_app()
    return app

if __name__ == '__main__':
    app = main()
    # Import socketio from app
    from app import socketio
    # Run with debug=False in production
    debug_mode = os.getenv('FLASK_ENV') != 'production'
    socketio.run(app, debug=debug_mode, host='127.0.0.1', port=5000)