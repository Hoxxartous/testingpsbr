# Ensure eventlet monkey patching happens first (for production)
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    pass

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# PostgreSQL driver compatibility - prefer psycopg2-binary if available
try:
    import psycopg2
except ImportError:
    # Fallback to psycopg if psycopg2 not available
    pass

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from config import Config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
socketio = SocketIO()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Your session has expired. Please log in again.'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'strong'  # Strong session protection
    socketio.init_app(app, cors_allowed_origins="*")
    
    # Initialize session manager for better session handling
    from app.session_manager import init_session_manager
    init_session_manager(app)
    
    # Handle 401 Unauthorized errors globally
    @app.errorhandler(401)
    def handle_unauthorized(error):
        """Handle 401 Unauthorized errors with session cleanup"""
        from flask import session, redirect, url_for, flash, request
        
        # Clear stale session data
        session.clear()
        
        # Log the unauthorized access
        app.logger.info(f"401 Unauthorized error handled for {request.url}")
        
        # Redirect to login with helpful message
        flash('Your session has expired. Please log in again.', 'info')
        return redirect(url_for('auth.login'))
    
    # Register blueprints
    from app.main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    
    from app.auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    
    from app.pos import pos as pos_blueprint
    app.register_blueprint(pos_blueprint, url_prefix='/pos')
    
    from app.admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint, url_prefix='/admin')
    
    from app.superuser import superuser as superuser_blueprint
    app.register_blueprint(superuser_blueprint, url_prefix='/superuser')
    
    from app.cashier import cashier as cashier_blueprint
    app.register_blueprint(cashier_blueprint, url_prefix='/cashier')
    
    # Register debug blueprint (for troubleshooting)
    from app.debug_routes import debug_bp
    app.register_blueprint(debug_bp)
    
    # User loader for Flask-Login with comprehensive error handling
    @login_manager.user_loader
    def load_user(user_id):
        """Load user with robust error handling and session cleanup"""
        if not user_id:
            return None
            
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            app.logger.warning(f"Invalid user_id format in session: {user_id}")
            return None
        
        # Add retry logic for SSL connection issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Import User model within the function to avoid circular imports
                from app.models import User
                from sqlalchemy import text
                
                # Check if database is accessible
                db.session.execute(text("SELECT 1")).scalar()
                
                # Load user from database
                user = User.query.get(user_id)
                if user and user.is_active:
                    return user
                elif user and not user.is_active:
                    app.logger.warning(f"Inactive user attempted to load session: {user.username}")
                    return None
                else:
                    app.logger.warning(f"User not found in database: {user_id}")
                    return None
                    
            except Exception as e:
                error_msg = str(e).lower()
                if attempt < max_retries - 1 and any(keyword in error_msg for keyword in ['ssl error', 'connection', 'timeout']):
                    app.logger.warning(f"Database connection error in user loader, retrying... ({attempt + 1}/{max_retries}): {e}")
                    import time
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    app.logger.error(f"User loader failed after {max_retries} attempts: {e}")
                    return None
        return None
    
    # Handle unauthorized access gracefully
    @login_manager.unauthorized_handler
    def unauthorized():
        """Handle unauthorized access with proper session cleanup"""
        from flask import request, session, redirect, url_for, flash
        
        # Clear any stale session data
        session.clear()
        
        # Log the unauthorized access attempt
        app.logger.info(f"Unauthorized access attempt from {request.remote_addr} to {request.url}")
        
        # Redirect to login with helpful message
        flash('Your session has expired. Please log in again.', 'info')
        return redirect(url_for('auth.login'))
    
    # Context processors for templates
    @app.context_processor
    def inject_user_branch_info():
        from flask_login import current_user
        if current_user.is_authenticated:
            return {
                'current_branch': current_user.branch,
                'accessible_branches': current_user.get_accessible_branches(),
                'is_super_user': current_user.is_super_user(),
                'is_branch_admin': current_user.is_branch_admin()
            }
        return {}
    
    # Template filters for timezone handling
    @app.template_filter('local_datetime')
    def local_datetime_filter(utc_datetime, format_str='%Y-%m-%d %H:%M:%S'):
        """Convert UTC datetime to local timezone and format it"""
        if not utc_datetime:
            return ''
        try:
            from app.models import TimezoneManager
            return TimezoneManager.format_local_time(utc_datetime, format_str)
        except Exception as e:
            app.logger.error(f"Error formatting datetime: {e}")
            return utc_datetime.strftime(format_str) if utc_datetime else ''
    
    @app.template_filter('local_date')
    def local_date_filter(utc_datetime):
        """Convert UTC datetime to local date"""
        if not utc_datetime:
            return ''
        try:
            from app.models import TimezoneManager
            return TimezoneManager.format_local_time(utc_datetime, '%Y-%m-%d')
        except Exception as e:
            app.logger.error(f"Error formatting date: {e}")
            return utc_datetime.strftime('%Y-%m-%d') if utc_datetime else ''
    
    @app.template_filter('local_time')
    def local_time_filter(utc_datetime):
        """Convert UTC datetime to local time"""
        if not utc_datetime:
            return ''
        try:
            from app.models import TimezoneManager
            return TimezoneManager.format_local_time(utc_datetime, '%H:%M:%S')
        except Exception as e:
            app.logger.error(f"Error formatting time: {e}")
            return utc_datetime.strftime('%H:%M:%S') if utc_datetime else ''
    
    # Additional specific format filters
    @app.template_filter('local_datetime_short')
    def local_datetime_short_filter(utc_datetime):
        """Convert UTC datetime to local timezone with short format"""
        if not utc_datetime:
            return ''
        try:
            from app.models import TimezoneManager
            return TimezoneManager.format_local_time(utc_datetime, '%Y-%m-%d %H:%M')
        except Exception as e:
            app.logger.error(f"Error formatting datetime: {e}")
            return utc_datetime.strftime('%Y-%m-%d %H:%M') if utc_datetime else ''
    
    @app.template_filter('local_time_short')
    def local_time_short_filter(utc_datetime):
        """Convert UTC datetime to local time with short format"""
        if not utc_datetime:
            return ''
        try:
            from app.models import TimezoneManager
            return TimezoneManager.format_local_time(utc_datetime, '%H:%M')
        except Exception as e:
            app.logger.error(f"Error formatting time: {e}")
            return utc_datetime.strftime('%H:%M') if utc_datetime else ''
    
    # Initialize database automatically on app startup
    def init_db():
        """Initialize database with multi-branch support automatically"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                app.logger.info(f"Database initialization attempt {attempt + 1}/{max_retries}")
                
                # Test basic database connection first
                from sqlalchemy import text
                db.session.execute(text("SELECT 1")).scalar()
                app.logger.info("Database connection successful")
                
                from sqlalchemy import inspect
                inspector = inspect(db.engine)
                existing_tables = inspector.get_table_names()
                app.logger.info(f"Found {len(existing_tables)} existing tables: {existing_tables}")
                
                # Check if database is completely empty or missing key tables
                if not existing_tables or 'users' not in existing_tables or 'branches' not in existing_tables:
                    app.logger.info("Database not initialized or incomplete, starting automatic initialization...")
                    print("=" * 60)
                    print("FIRST TIME SETUP - INITIALIZING DATABASE...")
                    print("=" * 60)
                    
                    from app.db_init import init_multibranch_db
                    init_multibranch_db(app)
                    
                    print("=" * 60)
                    print("DATABASE INITIALIZATION COMPLETED!")
                    print("Default Login Credentials:")
                    print("   Super Admin: superadmin / SuperAdmin123!")
                    print("   Branch Admin: admin1 / admin123")
                    print("   Cashier: cashier1_1 / cashier123")
                    print("=" * 60)
                    
                else:
                    # Double-check that we have actual data, not just empty tables
                    from app.models import Branch, User
                    branch_count = Branch.query.count()
                    user_count = User.query.count()
                    app.logger.info(f"Found {branch_count} branches and {user_count} users")
                    
                    if branch_count == 0 or user_count == 0:
                        app.logger.info(f"Incomplete data found (branches: {branch_count}, users: {user_count}), initializing missing data...")
                        print("INITIALIZING MISSING DATA...")
                        from app.db_init import init_multibranch_db
                        init_multibranch_db(app)
                        print("DATA INITIALIZATION COMPLETED!")
                    else:
                        app.logger.info(f"Database already initialized with data (branches: {branch_count}, users: {user_count})")
                
                # If we get here, initialization was successful
                break
                
            except Exception as e:
                app.logger.error(f"Database initialization attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    app.logger.info(f"Retrying in {retry_delay} seconds...")
                    import time
                    time.sleep(retry_delay)
                else:
                    app.logger.error("All database initialization attempts failed")
                    print(f"Database initialization failed after {max_retries} attempts: {str(e)}")
                    print("Please check your database configuration and try again.")
    
    # Configure logging
    configure_logging(app)
    
    # Call init_db when app starts
    with app.app_context():
        try:
            init_db()
        except Exception as e:
            app.logger.error(f"Startup database initialization failed: {str(e)}")
            print(f"Startup initialization failed: {str(e)}")
    
    return app

def configure_logging(app):
    """Configure application logging"""
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.mkdir('logs')
    
    # Set log level based on configuration
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO').upper())
    
    # Configure file handler for all logs with UTF-8 encoding
    file_handler = RotatingFileHandler('logs/restaurant_pos.log', maxBytes=10240000, backupCount=10, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(log_level)
    app.logger.addHandler(file_handler)
    
    # Configure console handler if LOG_TO_STDOUT is enabled with UTF-8 encoding
    if app.config.get('LOG_TO_STDOUT'):
        import sys
        # Use UTF-8 encoding for console output on Windows
        if sys.platform.startswith('win'):
            import io
            # Wrap stdout with UTF-8 encoding
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s'
        ))
        stream_handler.setLevel(log_level)
        app.logger.addHandler(stream_handler)
    
    # Set the application logger level
    app.logger.setLevel(log_level)
    
    # Log application startup
    app.logger.info('Restaurant POS application startup')
    app.logger.info(f'Log level set to: {app.config.get("LOG_LEVEL", "INFO")}')
    app.logger.info(f'Debug mode: {app.config.get("DEBUG", False)}')
