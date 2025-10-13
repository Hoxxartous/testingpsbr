from flask import render_template, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app.main import main
from app import db

@main.route('/')
def index():
    try:
        if current_user.is_authenticated:
            # Redirect based on user role
            if hasattr(current_user, 'role') and current_user.role:
                if current_user.role.name == 'SUPER_USER':
                    return redirect(url_for('superuser.dashboard'))
                elif current_user.role.name == 'BRANCH_ADMIN' or current_user.role.name == 'ADMIN':
                    return redirect(url_for('admin.dashboard'))
                else:
                    return redirect(url_for('pos.index'))
            else:
                return redirect(url_for('pos.index'))
        else:
            return redirect(url_for('auth.login'))
    except Exception:
        # Database might not be initialized yet, redirect to login
        return redirect(url_for('auth.login'))