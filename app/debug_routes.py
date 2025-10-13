"""
Debug routes for troubleshooting deployment issues
"""

from flask import Blueprint, jsonify, current_app
from app.models import User, Branch, UserRole
from app import db
from sqlalchemy import text

debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

@debug_bp.route('/db-status')
def db_status():
    """Check database status and user data"""
    try:
        # Test database connection
        result = db.session.execute(text("SELECT 1")).scalar()
        
        # Get user statistics
        user_count = User.query.count()
        branch_count = Branch.query.count()
        
        # Get sample users
        users = User.query.limit(10).all()
        user_list = []
        for user in users:
            user_list.append({
                'username': user.username,
                'role': user.role.value,
                'is_active': user.is_active,
                'has_password': bool(user.password_hash)
            })
        
        return jsonify({
            'status': 'success',
            'database_connected': True,
            'user_count': user_count,
            'branch_count': branch_count,
            'sample_users': user_list
        })
        
    except Exception as e:
        current_app.logger.error(f"Database status check failed: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'database_connected': False
        }), 500

@debug_bp.route('/test-login/<username>')
def test_login(username):
    """Test login functionality for a specific user"""
    try:
        user = User.query.filter_by(username=username).first()
        
        if not user:
            return jsonify({
                'status': 'error',
                'message': f'User {username} not found',
                'total_users': User.query.count()
            }), 404
        
        # Test with common passwords
        test_passwords = ['SuperAdmin123!', 'admin123', 'cashier123', 'waiter123']
        password_results = {}
        
        for pwd in test_passwords:
            password_results[pwd] = user.check_password(pwd)
        
        return jsonify({
            'status': 'success',
            'user': {
                'username': user.username,
                'role': user.role.value,
                'is_active': user.is_active,
                'has_password_hash': bool(user.password_hash),
                'password_hash_preview': user.password_hash[:20] + '...' if user.password_hash else None
            },
            'password_tests': password_results
        })
        
    except Exception as e:
        current_app.logger.error(f"Test login failed: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500

@debug_bp.route('/init-db')
def init_database():
    """Manually initialize the database"""
    try:
        current_app.logger.info("Manual database initialization requested")
        
        # Check current state
        from sqlalchemy import text, inspect
        
        # Test connection
        db.session.execute(text("SELECT 1")).scalar()
        
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        from app.models import Branch, User
        branch_count = Branch.query.count() if 'branches' in existing_tables else 0
        user_count = User.query.count() if 'users' in existing_tables else 0
        
        if branch_count > 0 or user_count > 0:
            return jsonify({
                'status': 'info',
                'message': 'Database already initialized',
                'branch_count': branch_count,
                'user_count': user_count,
                'tables': existing_tables
            })
        
        # Initialize database
        current_app.logger.info("Starting manual database initialization...")
        from app.db_init import init_multibranch_db
        init_multibranch_db(current_app)
        
        # Verify initialization
        new_branch_count = Branch.query.count()
        new_user_count = User.query.count()
        
        return jsonify({
            'status': 'success',
            'message': 'Database initialized successfully',
            'branch_count': new_branch_count,
            'user_count': new_user_count,
            'tables': inspector.get_table_names(),
            'credentials': {
                'superadmin': 'SuperAdmin123!',
                'admin1': 'admin123',
                'cashier1_1': 'cashier123'
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Manual database initialization failed: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'message': 'Database initialization failed'
        }), 500
