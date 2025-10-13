"""
Session Management Utilities for Restaurant POS
Handles session cleanup and prevents unauthorized errors
"""

from flask import current_app, session, request
from flask_login import current_user
from datetime import datetime, timedelta
import logging

class SessionManager:
    """Manages user sessions and prevents stale session issues"""
    
    @staticmethod
    def cleanup_stale_sessions():
        """Clean up stale session data"""
        try:
            # Clear session if it contains invalid data
            if 'user_id' in session:
                user_id = session.get('user_id')
                if not user_id or not str(user_id).isdigit():
                    current_app.logger.warning(f"Invalid user_id in session: {user_id}, clearing session")
                    session.clear()
                    return True
            
            # Check for expired sessions
            if '_permanent' in session and session.get('_permanent'):
                # Check if session has expired based on permanent session lifetime
                last_activity = session.get('_last_activity')
                if last_activity:
                    try:
                        last_activity = datetime.fromisoformat(last_activity)
                        session_lifetime = current_app.config.get('PERMANENT_SESSION_LIFETIME', timedelta(hours=1))
                        if datetime.utcnow() - last_activity > session_lifetime:
                            current_app.logger.info("Session expired, clearing stale session data")
                            session.clear()
                            return True
                    except (ValueError, TypeError) as e:
                        current_app.logger.warning(f"Invalid last_activity format: {e}, clearing session")
                        session.clear()
                        return True
            
            return False
            
        except Exception as e:
            current_app.logger.error(f"Error during session cleanup: {e}")
            session.clear()
            return True
    
    @staticmethod
    def update_session_activity():
        """Update session activity timestamp"""
        try:
            if current_user.is_authenticated:
                session['_last_activity'] = datetime.utcnow().isoformat()
                session.permanent = True  # Make session permanent for proper timeout handling
        except Exception as e:
            current_app.logger.error(f"Error updating session activity: {e}")
    
    @staticmethod
    def validate_session():
        """Validate current session and clean if necessary"""
        try:
            # Check if user is authenticated but session is invalid
            if current_user.is_authenticated:
                try:
                    # Validate that the user still exists and is active
                    from app.models import User
                    user = User.query.get(current_user.id)
                    if not user or not user.is_active:
                        current_app.logger.warning(f"User {current_user.id} no longer exists or is inactive, clearing session")
                        session.clear()
                        return False
                except Exception as e:
                    current_app.logger.error(f"Error validating user in session: {e}")
                    session.clear()
                    return False
                
                # Update activity
                SessionManager.update_session_activity()
                return True
            
            # Clean up any stale session data for unauthenticated users
            return not SessionManager.cleanup_stale_sessions()
            
        except Exception as e:
            current_app.logger.error(f"Error validating session: {e}")
            session.clear()
            return False

def init_session_manager(app):
    """Initialize session manager with Flask app"""
    
    @app.before_request
    def before_request():
        """Run before each request to validate sessions"""
        # Skip session validation for static files and auth endpoints
        if (request.endpoint and 
            (request.endpoint.startswith('static') or 
             request.endpoint == 'auth.login' or
             request.endpoint == 'auth.logout')):
            return
        
        # Validate and clean session
        SessionManager.validate_session()
    
    @app.after_request
    def after_request(response):
        """Run after each request to update session activity"""
        # Update session activity for authenticated users
        if current_user.is_authenticated:
            SessionManager.update_session_activity()
        
        return response
    
    app.logger.info("Session manager initialized")
