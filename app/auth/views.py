from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.auth import auth
from app.models import User, AuditLog, UserRole
from app import db
from datetime import datetime
import pytz

@auth.route('/login', methods=['GET', 'POST'])
def login():
    # Clear any stale session data on login page access
    if not current_user.is_authenticated and request.method == 'GET':
        from flask import session
        session.clear()
    
    if current_user.is_authenticated:
        current_app.logger.info(f"Already authenticated user {current_user.username} attempted to access login page")
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember_me = bool(request.form.get('remember_me'))
        
        current_app.logger.info(f"Login attempt for username: {username}")
        
        try:
            # Ensure database is initialized before querying
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            
            if 'users' not in existing_tables:
                # Database not initialized, initialize it now
                current_app.logger.info("Database not initialized, initializing now...")
                from app.db_init import init_db_lazy
                init_db_lazy(current_app)
            
            user = User.query.filter_by(username=username).first()
            
            # Debug logging
            if user:
                current_app.logger.info(f"User found: {user.username}, Active: {user.is_active}, Role: {user.role.value}")
                password_valid = user.check_password(password)
                current_app.logger.info(f"Password validation result: {password_valid}")
            else:
                current_app.logger.warning(f"User not found: {username}")
                # Check if any users exist at all
                user_count = User.query.count()
                current_app.logger.info(f"Total users in database: {user_count}")
            
            if user and user.check_password(password) and user.is_active:
                # Clear any existing session data before login
                from flask import session
                session.clear()
                
                # Login user with proper session management
                login_user(user, remember=remember_me)
                
                # Update last login time
                user.last_login = datetime.utcnow()
                db.session.commit()
                
                # Log the login action
                log_audit_action(user.id, 'login', 'User logged in successfully')
                current_app.logger.info(f"Successful login for user: {username} (Role: {user.role.value})")
                
                # Redirect to appropriate dashboard based on role
                if user.role == UserRole.SUPER_USER:
                    return redirect(url_for('superuser.dashboard'))
                elif user.role == UserRole.BRANCH_ADMIN:
                    return redirect(url_for('admin.dashboard'))
                else:
                    return redirect(url_for('pos.index'))
            else:
                current_app.logger.warning(f"Failed login attempt for username: {username}")
                flash('Invalid username or password', 'error')
                
        except Exception as e:
            current_app.logger.error(f"Login error: {str(e)}")
            flash('System error occurred. Please try again.', 'error')
    
    return render_template('auth/login.html')

@auth.route('/logout')
@login_required
def logout():
    username = current_user.username
    # Log the logout action
    log_audit_action(current_user.id, 'logout', 'User logged out')
    current_app.logger.info(f"User logged out: {username}")
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))

def log_audit_action(user_id, action, description):
    """Helper function to log audit actions"""
    try:
        # Get client IP
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.environ.get('REMOTE_ADDR')
        
        # Create audit log entry
        audit_log = AuditLog(
            user_id=user_id,
            action=action,
            description=description,
            ip_address=ip_address,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.add(audit_log)
        db.session.commit()
    except Exception as e:
        # Log the error but don't break the main flow
        current_app.logger.error(f"Audit log error: {str(e)}")
        db.session.rollback()