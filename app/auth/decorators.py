"""
Authentication and Authorization Decorators
Provides role-based access control and branch isolation
"""

from functools import wraps
from flask import abort, request, current_app
from flask_login import current_user
from app.models import UserRole

def login_required_with_role(*allowed_roles):
    """
    Decorator that requires login and specific roles
    Usage: @login_required_with_role(UserRole.SUPER_USER, UserRole.BRANCH_ADMIN)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)  # Unauthorized
            
            if current_user.role not in allowed_roles:
                current_app.logger.warning(f"Access denied for user {current_user.username} with role {current_user.role.value}")
                abort(403)  # Forbidden
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def super_admin_required(f):
    """Decorator that requires super admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        
        if current_user.role != UserRole.SUPER_USER:
            current_app.logger.warning(f"Super admin access denied for user {current_user.username}")
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def branch_admin_required(f):
    """Decorator that requires branch admin role or super user"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        
        # Allow both super users and branch admins
        allowed_roles = [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]
        if current_user.role not in allowed_roles:
            current_app.logger.warning(f"Branch admin access denied for user {current_user.username}")
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def cashier_or_above_required(f):
    """Decorator that requires cashier role or above"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        
        allowed_roles = [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN, UserRole.CASHIER]
        if current_user.role not in allowed_roles:
            current_app.logger.warning(f"Cashier+ access denied for user {current_user.username}")
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def pos_access_required(f):
    """Decorator that allows POS access for cashiers and waiters"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        
        # Allow cashiers, waiters, and admin roles to access POS
        allowed_roles = [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN, UserRole.CASHIER, UserRole.WAITER]
        if current_user.role not in allowed_roles:
            current_app.logger.warning(f"POS access denied for user {current_user.username} with role {current_user.role.value}")
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def branch_isolation_required(f):
    """
    Decorator that ensures branch isolation
    Super users can access all branches, others only their own branch
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        
        # Super users can access everything
        if current_user.role == UserRole.SUPER_USER:
            return f(*args, **kwargs)
        
        # Get branch_id from URL parameters or request data
        branch_id = None
        
        # Try to get branch_id from URL parameters
        if 'branch_id' in kwargs:
            branch_id = kwargs['branch_id']
        elif 'branch_id' in request.args:
            branch_id = request.args.get('branch_id', type=int)
        elif 'branch_id' in request.form:
            branch_id = request.form.get('branch_id', type=int)
        elif request.is_json and request.json and 'branch_id' in request.json:
            branch_id = request.json.get('branch_id')
        
        # If no branch_id specified, use user's branch
        if branch_id is None:
            # For routes that don't specify branch_id, use user's branch
            return f(*args, **kwargs)
        
        # Check if user can access this branch
        if branch_id != current_user.branch_id:
            current_app.logger.warning(f"Branch isolation violation: User {current_user.username} (branch {current_user.branch_id}) tried to access branch {branch_id}")
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function

def get_user_branch_filter():
    """
    Helper function to get branch filter for queries
    Returns None for super users (no filter), branch_id for others
    """
    if not current_user.is_authenticated:
        return None
    
    if current_user.role == UserRole.SUPER_USER:
        return None  # No filter - can see all branches
    
    return current_user.branch_id

def filter_by_user_branch(query, model_class):
    """
    Helper function to filter queries by user's branch
    Usage: filter_by_user_branch(Order.query, Order)
    """
    if not current_user.is_authenticated:
        return query.filter(False)  # Return empty result
    
    if current_user.role == UserRole.SUPER_USER:
        return query  # No filter - can see all branches
    
    # Filter by user's branch
    return query.filter(model_class.branch_id == current_user.branch_id)
