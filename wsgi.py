# CRITICAL: Monkey patch eventlet BEFORE any other imports
import eventlet
eventlet.monkey_patch()

import os
import logging
from app import create_app, socketio
from config import Config

# Create the app using the same configuration as run.py (default Config)
# but optimized for Gunicorn deployment
app = create_app(Config)

# Configure logging for Gunicorn
if __name__ != "__main__":
    # When running under Gunicorn, use Gunicorn's logger
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

# For production deployment with Gunicorn, we need to ensure proper
# database initialization and WebSocket handling
def init_db():
    """Initialize database if needed"""
    try:
        from app.models import User, Branch, MenuItem, Order, OrderItem
        from app import db
        
        # Create tables if they don't exist
        with app.app_context():
            db.create_all()
            app.logger.info("Database tables initialized successfully")
    except Exception as e:
        app.logger.error(f"Database initialization error: {e}")

# Initialize database on startup (only once per worker)
with app.app_context():
    init_db()

# Expose the socketio app for Gunicorn
# Gunicorn will use this when running with eventlet worker
application = socketio

if __name__ == "__main__":
    # Development mode - use socketio.run() for WebSocket support
    print("Starting Restaurant POS application in development mode...")
    print("Server will be available at: http://127.0.0.1:5000")
    print("For production, use: gunicorn -c gunicorn.conf.py wsgi:application")
    socketio.run(app, host='127.0.0.1', port=5000, debug=True)