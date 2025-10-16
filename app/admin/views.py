from flask import render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from app.admin import admin
from app.models import User, MenuItem, Category, Order, AuditLog, Table, Customer, UserRole, OrderItem, DeliveryCompany, ServiceType, OrderStatus, TimezoneManager, AdminPinCode, WaiterCashierAssignment, OrderEditHistory, ManualCardPayment
from app import db
from app.auth.decorators import branch_admin_required, filter_by_user_branch, get_user_branch_filter
from datetime import datetime, timedelta
from sqlalchemy import func, and_
import enum

@admin.before_request
@branch_admin_required
def before_request():
    # Access control is handled by the decorator
    pass

@admin.route('/dashboard')
def dashboard():
    # Use helper functions for branch filtering
    branch_filter = get_user_branch_filter()
    
    # Base queries with branch filtering - separate paid and unpaid orders
    total_orders = filter_by_user_branch(Order.query, Order).count()  # ALL orders (including PENDING)
    total_paid_orders = filter_by_user_branch(Order.query.filter(Order.status == OrderStatus.PAID), Order).count()
    total_unpaid_orders = filter_by_user_branch(Order.query.filter(Order.status == OrderStatus.PENDING), Order).count()
    
    # Today's statistics - separate paid and unpaid
    today = datetime.utcnow().date()
    today_filter = func.date(Order.created_at) == today
    
    today_query = filter_by_user_branch(Order.query.filter(today_filter), Order)
    today_orders = today_query.count()  # ALL orders today
    
    today_paid_query = filter_by_user_branch(
        Order.query.filter(today_filter, Order.status == OrderStatus.PAID), 
        Order
    )
    today_paid_orders = today_paid_query.count()
    
    today_unpaid_query = filter_by_user_branch(
        Order.query.filter(today_filter, Order.status == OrderStatus.PENDING), 
        Order
    )
    today_unpaid_orders = today_unpaid_query.count()
    
    # Today's revenue - only from PAID orders
    sales_query = db.session.query(func.sum(Order.total_amount)).filter(
        today_filter,
        Order.status == OrderStatus.PAID
    )
    if branch_filter:
        sales_query = sales_query.filter(Order.branch_id == branch_filter)
    today_sales = sales_query.scalar() or 0
    
    # Total revenue (all time) - only from PAID orders
    revenue_query = db.session.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.PAID)
    if branch_filter:
        revenue_query = revenue_query.filter(Order.branch_id == branch_filter)
    total_revenue = revenue_query.scalar() or 0
    
    # Include manual card payments in revenue calculations
    manual_card_total_today = 0
    manual_card_total_all_time = 0
    
    if branch_filter:
        # For branch admin, get manual card payments for their branch
        manual_card_total_today = ManualCardPayment.get_total_for_date_and_branch(today, branch_filter)
        manual_card_total_all_time = ManualCardPayment.get_total_for_date_range_and_branch(
            datetime(2020, 1, 1).date(), today, branch_filter
        )
    else:
        # For super user accessing admin dashboard, get all manual card payments
        manual_card_total_today = db.session.query(func.sum(ManualCardPayment.amount)).filter(
            ManualCardPayment.date == today
        ).scalar() or 0
        manual_card_total_all_time = db.session.query(func.sum(ManualCardPayment.amount)).scalar() or 0
    
    # Update totals to include manual card payments
    today_sales_with_cards = today_sales + manual_card_total_today
    total_revenue_with_cards = total_revenue + manual_card_total_all_time
    
    # Calculate cash amounts (total revenue - card payments)
    today_cash_amount = today_sales  # This is from orders only (cash payments)
    total_cash_amount = total_revenue  # This is from orders only (cash payments)
    
    # Recent orders (branch-filtered)
    orders_query = filter_by_user_branch(Order.query, Order)
    recent_orders = orders_query.order_by(Order.created_at.desc()).limit(10).all()
    
    # Recent audit logs (branch-filtered)
    if current_user.role == UserRole.SUPER_USER:
        recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()
    else:
        # Get user IDs from the same branch for audit log filtering
        branch_user_ids = [u.id for u in filter_by_user_branch(User.query, User).all()]
        recent_logs = AuditLog.query.filter(AuditLog.user_id.in_(branch_user_ids)).order_by(AuditLog.created_at.desc()).limit(10).all()
    
    # Sales by day for the last 7 days (for chart)
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    # Daily sales query with branch filtering
    daily_sales_query = db.session.query(
        func.date(Order.created_at).label('date'),
        func.sum(Order.total_amount).label('total')
    ).filter(
        Order.created_at >= start_date
    )
    if branch_filter:
        daily_sales_query = daily_sales_query.filter(Order.branch_id == branch_filter)
    
    daily_sales = daily_sales_query.group_by(
        func.date(Order.created_at)
    ).order_by(
        func.date(Order.created_at)
    ).all()
    
    # Top selling items (branch-filtered)
    top_items_query = db.session.query(
        MenuItem.name,
        func.sum(OrderItem.quantity).label('total_quantity'),
        func.sum(OrderItem.total_price).label('total_revenue')
    ).join(OrderItem, MenuItem.id == OrderItem.menu_item_id)\
     .join(Order, OrderItem.order_id == Order.id)\
     .filter(Order.created_at >= start_date)
    
    if branch_filter:
        top_items_query = top_items_query.filter(Order.branch_id == branch_filter)
    
    top_items = top_items_query.group_by(MenuItem.id, MenuItem.name)\
                              .order_by(func.sum(OrderItem.quantity).desc())\
                              .limit(5).all()
    
    # Get waiter-specific statistics for admin's branch (aggregated across all cashiers in branch)
    waiter_stats = {}
    
    # Get all cashiers in admin's branch
    branch_cashiers = User.query.filter_by(
        role=UserRole.CASHIER,
        branch_id=current_user.branch_id,
        is_active=True
    ).all()
    
    cashier_ids = [cashier.id for cashier in branch_cashiers]
    
    if cashier_ids:
        # Get waiter orders statistics for today (all orders assigned to cashiers in this branch)
        waiter_orders_today = Order.query.filter(
            Order.assigned_cashier_id.in_(cashier_ids),
            Order.notes.like('%[WAITER ORDER]%'),
            func.date(Order.created_at) == today,
            Order.branch_id == current_user.branch_id  # Additional branch filtering
        ).count()
        
        # Get waiter sales today (only PAID orders)
        waiter_sales_today = db.session.query(func.sum(Order.total_amount)).filter(
            Order.assigned_cashier_id.in_(cashier_ids),
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PAID,
            func.date(Order.created_at) == today,
            Order.branch_id == current_user.branch_id  # Additional branch filtering
        ).scalar() or 0
        
        # Get pending waiter orders (all pending waiter orders in branch)
        pending_waiter_orders = Order.query.filter(
            Order.assigned_cashier_id.in_(cashier_ids),
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PENDING,
            Order.branch_id == current_user.branch_id  # Additional branch filtering
        ).count()
        
        waiter_stats = {
            'orders_today': waiter_orders_today,
            'sales_today': float(waiter_sales_today),
            'pending_orders': pending_waiter_orders
        }
    else:
        # No cashiers in branch
        waiter_stats = {
            'orders_today': 0,
            'sales_today': 0.0,
            'pending_orders': 0
        }
    
    # Get edited orders statistics for today (branch-filtered)
    edited_orders_today_query = filter_by_user_branch(
        Order.query.filter(
            today_filter,
            Order.edit_count > 0
        ), 
        Order
    )
    edited_orders_today = edited_orders_today_query.count()
    
    # Get total edited orders (all time, branch-filtered)
    total_edited_orders_query = filter_by_user_branch(
        Order.query.filter(Order.edit_count > 0), 
        Order
    )
    total_edited_orders = total_edited_orders_query.count()
    
    # Get branch info for display
    branch_info = None
    if current_user.branch_id:
        from app.models import Branch
        branch_info = Branch.query.get(current_user.branch_id)
    
    # Get top cashiers by order edits this week (branch-filtered)
    week_start = datetime.utcnow() - timedelta(days=7)
    
    # Query to get cashiers with their edit counts this week
    top_editing_cashiers_query = db.session.query(
        User.id,
        User.first_name,
        User.last_name,
        func.count(OrderEditHistory.id).label('edit_count')
    ).join(
        OrderEditHistory, User.id == OrderEditHistory.edited_by
    ).join(
        Order, OrderEditHistory.order_id == Order.id
    ).filter(
        User.role == UserRole.CASHIER,
        OrderEditHistory.edited_at >= week_start
    )
    
    # Apply branch filtering for admin users
    if current_user.role == UserRole.BRANCH_ADMIN and current_user.branch_id:
        top_editing_cashiers_query = top_editing_cashiers_query.filter(
            User.branch_id == current_user.branch_id
        )
    
    # Group by cashier and order by edit count
    top_editing_cashiers_raw = top_editing_cashiers_query.group_by(
        User.id, User.first_name, User.last_name
    ).order_by(
        func.count(OrderEditHistory.id).desc()
    ).limit(6).all()
    
    # Format the data for the chart
    top_editing_cashiers = []
    for cashier in top_editing_cashiers_raw:
        full_name = f"{cashier.first_name} {cashier.last_name}".strip()
        if not full_name:
            full_name = f"Cashier {cashier.id}"
        
        top_editing_cashiers.append({
            'full_name': full_name,
            'edit_count': cashier.edit_count
        })
    
    return render_template('admin/dashboard.html',
                          total_orders=total_orders,
                          total_paid_orders=total_paid_orders,
                          total_unpaid_orders=total_unpaid_orders,
                          today_orders=today_orders,
                          today_paid_orders=today_paid_orders,
                          today_unpaid_orders=today_unpaid_orders,
                          today_sales=today_sales_with_cards,
                          total_revenue=total_revenue_with_cards,
                          recent_orders=recent_orders,
                          recent_logs=recent_logs,
                          daily_sales=daily_sales,
                          top_items=top_items,
                          waiter_stats=waiter_stats,
                          branch_info=branch_info,
                          edited_orders_today=edited_orders_today,
                          total_edited_orders=total_edited_orders,
                          top_editing_cashiers=top_editing_cashiers,
                          manual_card_total_today=manual_card_total_today,
                          manual_card_total_all_time=manual_card_total_all_time,
                          today_cash_amount=today_cash_amount,
                          total_cash_amount=total_cash_amount)

@admin.route('/users')
def users():
    """View users from admin's branch with filtering"""
    # Get filter parameters
    role = request.args.get('role')
    status = request.args.get('status')
    
    # Get branch-specific users using helper function
    users_query = filter_by_user_branch(User.query, User)
    
    # Branch admins should not see super admins, only their subordinates
    if current_user.role == UserRole.BRANCH_ADMIN:
        users_query = users_query.filter(User.role != UserRole.SUPER_USER)
    
    # Apply filters
    if role and role != 'all':
        users_query = users_query.filter(User.role == UserRole[role.upper()])
    
    if status and status != 'all':
        if status == 'active':
            users_query = users_query.filter(User.is_active == True)
        elif status == 'inactive':
            users_query = users_query.filter(User.is_active == False)
    
    users = users_query.order_by(User.created_at.desc()).all()
    
    # Determine user permissions - now branch admins can also manage users
    can_manage_users = current_user.role in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]
    can_view_only = False  # Both super users and branch admins can manage users
    
    # Get branches for super users, current branch for branch admins
    branches = []
    if current_user.role == UserRole.SUPER_USER:
        from app.models import Branch
        branches = Branch.query.filter_by(is_active=True).all()
    elif current_user.role == UserRole.BRANCH_ADMIN:
        from app.models import Branch
        branches = [current_user.branch] if current_user.branch else []
    
    return render_template('admin/users.html', 
                         users=users, 
                         can_manage_users=can_manage_users,
                         can_view_only=can_view_only,
                         branches=branches,
                         current_role=role,
                         current_status=status)

@admin.route('/create_user', methods=['POST'])
def create_user():
    # Both super admins and branch admins can create users
    if current_user.role not in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
        return jsonify({'success': False, 'message': 'Access denied. Admin privileges required.'}), 403
    try:
        # Get user data from request
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'email', 'first_name', 'last_name', 'role', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'Missing required field: {field}'}), 400
        
        # Check if username or email already exists
        existing_user = User.query.filter(
            (User.username == data['username']) | (User.email == data['email'])
        ).first()
        
        if existing_user:
            return jsonify({'success': False, 'message': 'Username or email already exists'}), 400
        
        # Create new user - branch admins can only create users in their branch
        if current_user.role == UserRole.BRANCH_ADMIN:
            # Branch admin can only create users in their own branch
            branch_id = current_user.branch_id
            # Branch admin cannot create super users or other branch admins
            if data['role'] in ['super_user', 'branch_admin']:
                return jsonify({'success': False, 'message': 'Branch admins cannot create super users or other branch admins'}), 403
        else:
            # Super user can create users in any branch
            branch_id = data.get('branch_id', current_user.branch_id)
        
        user = User(
            username=data['username'],
            email=data['email'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            role=UserRole(data['role']),
            branch_id=branch_id
        )
        user.set_password(data['password'])
        
        # Save to database
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role.value,
                'is_active': user.is_active,
                'created_at': TimezoneManager.format_local_time(user.created_at, '%Y-%m-%d %H:%M:%S')
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/update_user/<int:user_id>', methods=['POST'])
def update_user(user_id):
    # Both super admins and branch admins can update users
    if current_user.role not in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
        return jsonify({'success': False, 'message': 'Access denied. Admin privileges required.'}), 403
    try:
        # Get user data from request
        data = request.get_json()
        
        # Find user
        user = User.query.get_or_404(user_id)
        
        # Branch admins can only modify users in their own branch
        if current_user.role == UserRole.BRANCH_ADMIN:
            if user.branch_id != current_user.branch_id:
                return jsonify({'success': False, 'message': 'Access denied. You can only modify users in your branch.'}), 403
            # Branch admins cannot modify super users or other branch admins
            if user.role in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
                return jsonify({'success': False, 'message': 'Branch admins cannot modify super users or other branch admins'}), 403
        
        # Prevent modifying super users (for super users editing other super users)
        if user.role == UserRole.SUPER_USER and user.id != current_user.id:
            return jsonify({'success': False, 'message': 'Cannot modify other super users'}), 403
        
        # Update user fields - both super users and branch admins can edit basic fields
        if 'username' in data:
            # Check if username already exists for another user
            existing_user = User.query.filter(
                User.username == data['username'],
                User.id != user_id
            ).first()
            if existing_user:
                return jsonify({'success': False, 'message': 'Username already exists'}), 400
            user.username = data['username']
        
        if 'first_name' in data:
            user.first_name = data['first_name']
            
        if 'last_name' in data:
            user.last_name = data['last_name']
        
        if 'email' in data:
            # Check if email already exists for another user
            existing_user = User.query.filter(
                User.email == data['email'],
                User.id != user_id
            ).first()
            if existing_user:
                return jsonify({'success': False, 'message': 'Email already exists'}), 400
            user.email = data['email']
            
        if 'role' in data:
            # Branch admins cannot change roles to super_user or branch_admin
            if current_user.role == UserRole.BRANCH_ADMIN:
                if data['role'] in ['super_user', 'branch_admin']:
                    return jsonify({'success': False, 'message': 'Branch admins cannot assign super user or branch admin roles'}), 403
            user.role = UserRole(data['role'])
            
        if 'branch_id' in data:
            # Branch admins cannot move users to other branches
            if current_user.role == UserRole.BRANCH_ADMIN:
                if int(data['branch_id']) != current_user.branch_id:
                    return jsonify({'success': False, 'message': 'Branch admins cannot move users to other branches'}), 403
            user.branch_id = data['branch_id']
            
        if 'is_active' in data:
            # Check if trying to activate a user from an inactive branch
            if data['is_active'] and not user.is_active and user.branch_id:
                from app.models import Branch
                branch = Branch.query.get(user.branch_id)
                if branch and not branch.is_active:
                    return jsonify({
                        'success': False, 
                        'message': f'Cannot activate user from inactive branch "{branch.name}". Please reactivate the branch first.'
                    }), 400
            user.is_active = data['is_active']
            
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        
        # Save to database
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'User updated successfully',
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role.value,
                'is_active': user.is_active,
                'created_at': TimezoneManager.format_local_time(user.created_at, '%Y-%m-%d %H:%M:%S')
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    # Both super admins and branch admins can manage user status
    if current_user.role not in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
        return jsonify({'success': False, 'message': 'Access denied. Admin privileges required.'}), 403
    try:
        # Find user
        user = User.query.get_or_404(user_id)
        
        # Prevent modifying the current user
        if user.id == current_user.id:
            return jsonify({'success': False, 'message': 'Cannot modify yourself'}), 400
        
        # Branch admins can only modify users in their own branch
        if current_user.role == UserRole.BRANCH_ADMIN:
            if user.branch_id != current_user.branch_id:
                return jsonify({'success': False, 'message': 'Access denied. You can only modify users in your branch.'}), 403
            # Branch admins cannot modify super users or other branch admins
            if user.role in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
                return jsonify({'success': False, 'message': 'Branch admins cannot modify super users or other branch admins'}), 403
        
        # Prevent modifying super users (for super users editing other super users)
        if user.role == UserRole.SUPER_USER and user.id != current_user.id:
            return jsonify({'success': False, 'message': 'Cannot modify other super users'}), 403
        
        # Check if trying to activate a user from an inactive branch
        if not user.is_active and user.branch_id:  # User is currently inactive and has a branch
            from app.models import Branch
            branch = Branch.query.get(user.branch_id)
            if branch and not branch.is_active:
                return jsonify({
                    'success': False, 
                    'message': f'Cannot activate user from inactive branch "{branch.name}". Please reactivate the branch first.'
                }), 400
        
        # Toggle user active status instead of deleting
        user.is_active = not user.is_active
        db.session.commit()
        
        status = 'activated' if user.is_active else 'deactivated'
        return jsonify({'success': True, 'message': f'User {status} successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/users/add', methods=['GET', 'POST'])
def add_user():
    """Add user endpoint - available for both super users and branch admins"""
    if current_user.role not in [UserRole.SUPER_USER, UserRole.BRANCH_ADMIN]:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('admin.users'))
    
    if request.method == 'POST':
        # Check if this is an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
        
        try:
            # Validate password confirmation
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            
            if password != confirm_password:
                error_msg = 'Passwords do not match!'
                if is_ajax:
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'error')
                branches = [current_user.branch] if current_user.role == UserRole.BRANCH_ADMIN else Branch.query.filter_by(is_active=True).all()
                return render_template('admin/add_user.html', branches=branches, roles=UserRole)
            
            # Check if username already exists
            existing_user = User.query.filter_by(username=request.form.get('username')).first()
            if existing_user:
                error_msg = 'Username already exists!'
                if is_ajax:
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'error')
                branches = [current_user.branch] if current_user.role == UserRole.BRANCH_ADMIN else Branch.query.filter_by(is_active=True).all()
                return render_template('admin/add_user.html', branches=branches, roles=UserRole)
            
            # Check if email already exists
            existing_email = User.query.filter_by(email=request.form.get('email')).first()
            if existing_email:
                error_msg = 'Email already exists!'
                if is_ajax:
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'error')
                branches = [current_user.branch] if current_user.role == UserRole.BRANCH_ADMIN else Branch.query.filter_by(is_active=True).all()
                return render_template('admin/add_user.html', branches=branches, roles=UserRole)
            
            # Get role and validate for branch admins
            role_str = request.form.get('role').upper()
            if current_user.role == UserRole.BRANCH_ADMIN:
                if role_str in ['SUPER_USER', 'BRANCH_ADMIN']:
                    error_msg = 'Branch admins cannot create super users or other branch admins!'
                    if is_ajax:
                        return jsonify({'success': False, 'message': error_msg}), 400
                    flash(error_msg, 'error')
                    branches = [current_user.branch]
                    return render_template('admin/add_user.html', branches=branches, roles=UserRole)
            
            # Determine branch_id
            if current_user.role == UserRole.BRANCH_ADMIN:
                branch_id = current_user.branch_id  # Branch admin can only create users in their branch
            else:
                branch_id = int(request.form.get('branch_id')) if request.form.get('branch_id') else None
            
            # Create user
            user = User(
                username=request.form.get('username'),
                email=request.form.get('email'),
                first_name=request.form.get('first_name'),
                last_name=request.form.get('last_name'),
                role=UserRole[role_str],
                branch_id=branch_id,
                can_access_multiple_branches=bool(request.form.get('can_access_multiple_branches')) if current_user.role == UserRole.SUPER_USER else False
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            success_msg = f'User "{user.username}" created successfully!'
            if is_ajax:
                return jsonify({'success': True, 'message': success_msg})
            
            flash(success_msg, 'success')
            return redirect(url_for('admin.users'))
            
        except Exception as e:
            db.session.rollback()
            error_msg = f'Error creating user: {str(e)}'
            if is_ajax:
                return jsonify({'success': False, 'message': error_msg}), 500
            flash(error_msg, 'error')
    
    # GET request - show form
    from app.models import Branch
    if current_user.role == UserRole.BRANCH_ADMIN:
        branches = [current_user.branch] if current_user.branch else []
    else:
        branches = Branch.query.filter_by(is_active=True).all()
    
    return render_template('admin/add_user.html', branches=branches, roles=UserRole)

@admin.route('/create_category', methods=['POST'])
@login_required
def create_category():
    try:
        # Get category data from request
        data = request.get_json()
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'message': 'Category name is required'}), 400
        
        # Check if category already exists in the same branch
        existing_category = Category.query.filter_by(name=data['name'], branch_id=current_user.branch_id).first()
        if existing_category:
            return jsonify({'success': False, 'message': 'Category already exists in this branch'}), 400
        
        # Create new category with branch assignment
        category = Category(
            name=data['name'],
            description=data.get('description', ''),
            branch_id=current_user.branch_id
        )
        
        # Save to database
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Category created successfully',
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'is_active': category.is_active
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/create_menu_item', methods=['POST'])
@login_required
def create_menu_item():
    try:
        # Get menu item data from request
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'category_id', 'price']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'Missing required field: {field}'}), 400
        
        # Check if menu item already exists in the same category
        existing_item = MenuItem.query.filter_by(
            name=data['name'], 
            category_id=int(data['category_id'])
        ).first()
        if existing_item:
            return jsonify({'success': False, 'message': 'Menu item already exists in this category'}), 400
        
        # Create new menu item with branch assignment
        menu_item = MenuItem(
            name=data['name'],
            category_id=int(data['category_id']),
            price=float(data['price']),
            description=data.get('description', ''),
            is_active=data.get('is_active', True),
            image_url=data.get('image_url', ''),
            is_vegetarian=data.get('is_vegetarian', False),
            is_vegan=data.get('is_vegan', False),
            card_color=data.get('card_color', '#ffffff'),
            size_flag=data.get('size_flag') or None,
            portion_type=data.get('portion_type') or None,
            visual_priority=data.get('visual_priority', 'normal'),
            branch_id=current_user.branch_id
        )
        
        # Save to database
        db.session.add(menu_item)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Menu item created successfully',
            'item': {
                'id': menu_item.id,
                'name': menu_item.name,
                'category_id': menu_item.category_id,
                'price': float(menu_item.price),
                'description': menu_item.description,
                'is_active': menu_item.is_active,
                'image_url': menu_item.image_url,
                'is_vegetarian': menu_item.is_vegetarian,
                'is_vegan': menu_item.is_vegan
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/update_category/<int:category_id>', methods=['POST'])
@login_required
def update_category(category_id):
    try:
        # Get category data from request
        data = request.get_json()
        
        # Find category
        category = Category.query.get_or_404(category_id)
        
        # Store the original active status
        original_is_active = category.is_active
        
        # Update category fields
        if 'name' in data:
            # Check if new name already exists in the same branch (excluding current category)
            existing_category = Category.query.filter_by(
                name=data['name'], 
                branch_id=current_user.branch_id
            ).filter(Category.id != category_id).first()
            if existing_category:
                return jsonify({'success': False, 'message': 'Category name already exists in this branch'}), 400
            category.name = data['name']
        if 'description' in data:
            category.description = data['description']
        if 'is_active' in data:
            new_is_active = data['is_active']
            category.is_active = new_is_active
            
            # If category status is changing, update all items in this category
            if original_is_active != new_is_active:
                if new_is_active:
                    # If category is being set to active, set all items in this category to active
                    MenuItem.query.filter_by(category_id=category_id).update({'is_active': True})
                else:
                    # If category is being set to inactive, set all items in this category to inactive
                    MenuItem.query.filter_by(category_id=category_id).update({'is_active': False})
        
        # Save to database
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Category updated successfully',
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'is_active': category.is_active
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    try:
        # Find category
        category = Category.query.get_or_404(category_id)
        
        # Check if category has menu items
        if category.items.count() > 0:
            return jsonify({'success': False, 'message': 'Cannot delete category with menu items. You can set it as inactive instead.'}), 400
        
        # Delete category
        db.session.delete(category)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Category deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/update_menu_item/<int:item_id>', methods=['POST'])
@login_required
def update_menu_item(item_id):
    try:
        # Get menu item data from request
        data = request.get_json()
        
        # Find menu item
        menu_item = MenuItem.query.get_or_404(item_id)
        
        # Store original values for synchronization
        original_name = menu_item.name
        original_price = menu_item.price
        
        # Update menu item fields
        if 'name' in data:
            new_name = data['name']
            # Check if new name already exists in the same category (excluding current item)
            existing_item = MenuItem.query.filter_by(
                name=new_name, 
                category_id=menu_item.category_id
            ).filter(MenuItem.id != item_id).first()
            if existing_item:
                return jsonify({'success': False, 'message': 'Menu item already exists in this category'}), 400
            
            # If name is changing, update all items with the same original name to have the new name and current price
            if new_name != original_name:
                MenuItem.query.filter_by(
                    name=original_name, 
                    branch_id=current_user.branch_id
                ).filter(MenuItem.id != item_id).update({
                    'name': new_name,
                    'price': original_price
                })
            
            menu_item.name = new_name
        if 'category_id' in data:
            # Check if item name already exists in the new category
            new_category_id = int(data['category_id'])
            if new_category_id != menu_item.category_id:
                existing_item = MenuItem.query.filter_by(
                    name=menu_item.name, 
                    category_id=new_category_id
                ).first()
                if existing_item:
                    return jsonify({'success': False, 'message': 'Menu item already exists in the target category'}), 400
            menu_item.category_id = new_category_id
        if 'price' in data:
            new_price = float(data['price'])
            menu_item.price = new_price
            
            # Price synchronization: Update all items with the same name across all categories in the same branch
            if new_price != original_price:
                MenuItem.query.filter_by(
                    name=original_name, 
                    branch_id=current_user.branch_id
                ).filter(MenuItem.id != item_id).update({'price': new_price})
        if 'description' in data:
            menu_item.description = data['description']
        if 'is_active' in data:
            menu_item.is_active = data['is_active']
        if 'image_url' in data:
            menu_item.image_url = data['image_url']
        if 'is_vegetarian' in data:
            menu_item.is_vegetarian = data['is_vegetarian']
        if 'is_vegan' in data:
            menu_item.is_vegan = data['is_vegan']
        if 'card_color' in data:
            menu_item.card_color = data['card_color']
        if 'size_flag' in data:
            menu_item.size_flag = data['size_flag'] or None
        if 'portion_type' in data:
            menu_item.portion_type = data['portion_type'] or None
        if 'visual_priority' in data:
            menu_item.visual_priority = data['visual_priority']
        
        # Save to database
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': 'Menu item updated successfully',
            'item': {
                'id': menu_item.id,
                'name': menu_item.name,
                'category_id': menu_item.category_id,
                'price': float(menu_item.price),
                'description': menu_item.description,
                'is_active': menu_item.is_active,
                'image_url': menu_item.image_url,
                'is_vegetarian': menu_item.is_vegetarian,
                'is_vegan': menu_item.is_vegan,
                'card_color': menu_item.card_color,
                'size_flag': menu_item.size_flag,
                'portion_type': menu_item.portion_type,
                'visual_priority': menu_item.visual_priority
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/delete_menu_item/<int:item_id>', methods=['POST'])
@login_required
def delete_menu_item(item_id):
    try:
        # Find menu item
        menu_item = MenuItem.query.get_or_404(item_id)
        
        # Check if this menu item has been used in any orders
        order_item_count = OrderItem.query.filter_by(menu_item_id=item_id).count()
        
        if order_item_count > 0:
            return jsonify({
                'success': False, 
                'message': f'Cannot delete menu item "{menu_item.name}" because it has been used in {order_item_count} order(s). You can set it as inactive instead.'
            }), 400
        
        # Delete menu item
        db.session.delete(menu_item)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Menu item deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin.route('/menu')
def menu():
    # Get filter parameters
    category_id = request.args.get('category_id', '')
    is_active = request.args.get('is_active', '')
    
    # Build query for items with branch filtering
    items_query = filter_by_user_branch(MenuItem.query, MenuItem)
    
    # Apply filters
    if category_id:
        items_query = items_query.filter(MenuItem.category_id == category_id)
    if is_active:
        items_query = items_query.filter(MenuItem.is_active == (is_active == 'true'))
    
    # Get filtered items
    items = items_query.all()
    
    # Get categories for filter with branch filtering
    categories = filter_by_user_branch(Category.query, Category).all()
    
    # Get active categories for the add item form with branch filtering
    active_categories = filter_by_user_branch(
        Category.query.filter_by(is_active=True), 
        Category
    ).all()
    
    return render_template('admin/menu.html', 
                          categories=categories, 
                          active_categories=active_categories,
                          items=items,
                          filters={
                              'category_id': category_id,
                              'is_active': is_active
                          })

@admin.route('/orders')
def orders():
    # Get filter parameters
    table_id = request.args.get('table_id', '')
    cashier_id = request.args.get('cashier_id', '')
    service_type = request.args.get('service_type', '')
    delivery_company = request.args.get('delivery_company', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Build query with branch filtering
    query = filter_by_user_branch(Order.query, Order)
    
    # Apply filters
    if table_id:
        query = query.filter(Order.table_id == table_id)
    if cashier_id:
        query = query.filter(Order.cashier_id == cashier_id)
    if service_type:
        # Convert string to enum for filtering
        from app.models import ServiceType
        try:
            service_enum = ServiceType(service_type)
            query = query.filter(Order.service_type == service_enum)
        except ValueError:
            # Invalid service type, skip filtering
            pass
    if delivery_company:
        # Filter by delivery company using the new model
        delivery_company_obj = DeliveryCompany.query.filter_by(value=delivery_company).first()
        if delivery_company_obj:
            query = query.filter(Order.delivery_company_id == delivery_company_obj.id)
    if date_from:
        query = query.filter(Order.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        query = query.filter(Order.created_at <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    
    # Get paginated orders
    orders = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    
    # Get filter options (branch-specific)
    tables = filter_by_user_branch(
        Table.query.filter_by(is_active=True), 
        Table
    ).all()
    cashiers = filter_by_user_branch(
        User.query.filter_by(role=UserRole.CASHIER), 
        User
    ).all()
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        orders_data = []
        for order in orders.items:
            # Count regular items (excluding special items)
            regular_items_count = sum(1 for item in order.order_items if 'طلبات خاصة' not in item.menu_item.name)
            
            # Get delivery company info
            delivery_company_info = None
            if order.delivery_company_id and hasattr(order, 'delivery_company_info'):
                delivery_company_info = {
                    'name': order.delivery_company_info.name,
                    'value': order.delivery_company_info.value,
                    'icon': order.delivery_company_info.icon
                }
            
            orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'order_counter': order.order_counter if order.order_counter else None,
                'table_number': order.table.table_number if order.table else 'N/A',
                'cashier_name': order.cashier.username if order.cashier else 'N/A',
                'total_amount': float(order.total_amount),
                'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
                'service_type': order.service_type.value if order.service_type else 'on_table',
                'delivery_company': delivery_company_info,
                'regular_items_count': regular_items_count
            })
        
        return jsonify({
            'orders': orders_data,
            'pagination': {
                'page': orders.page,
                'pages': orders.pages,
                'per_page': orders.per_page,
                'total': orders.total,
                'has_prev': orders.has_prev,
                'has_next': orders.has_next,
                'prev_num': orders.prev_num,
                'next_num': orders.next_num
            }
        })
    
    return render_template('admin/orders.html', 
                          orders=orders,
                          tables=tables,
                          cashiers=cashiers,
                          filters={
                              'table_id': table_id,
                              'cashier_id': cashier_id,
                              'service_type': service_type,
                              'delivery_company': delivery_company,
                              'date_from': date_from,
                              'date_to': date_to
                          })

@admin.route('/audit_logs')
def audit_logs():
    # Get filter parameters
    user_id = request.args.get('user_id', '')
    action = request.args.get('action', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Build query with branch filtering (only show logs from users in the same branch)
    if current_user.role == UserRole.SUPER_USER:
        query = AuditLog.query
    else:
        # Get user IDs from the same branch
        branch_user_ids = [u.id for u in filter_by_user_branch(User.query, User).all()]
        query = AuditLog.query.filter(AuditLog.user_id.in_(branch_user_ids))
    
    # Apply filters
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if date_from:
        query = query.filter(AuditLog.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        query = query.filter(AuditLog.created_at <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    
    # Get paginated logs
    logs = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    
    # Get users for filter (branch-specific)
    users = filter_by_user_branch(User.query, User).all()
    
    # Get unique actions for filter
    actions = db.session.query(AuditLog.action).distinct().all()
    actions = [action[0] for action in actions]
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        logs_data = []
        for log in logs.items:
            logs_data.append({
                'id': log.id,
                'user': {
                    'username': log.user.username if log.user else 'System',
                    'full_name': log.user.get_full_name() if log.user else ''
                },
                'action': log.action,
                'description': log.description or '',
                'ip_address': log.ip_address or 'N/A',
                'created_at': {
                    'date': log.created_at.strftime('%Y-%m-%d'),
                    'time': log.created_at.strftime('%H:%M:%S')
                }
            })
        
        return jsonify({
            'logs': logs_data,
            'pagination': {
                'page': logs.page,
                'pages': logs.pages,
                'per_page': logs.per_page,
                'total': logs.total,
                'has_prev': logs.has_prev,
                'has_next': logs.has_next,
                'prev_num': logs.prev_num,
                'next_num': logs.next_num
            }
        })
    
    return render_template('admin/audit_logs.html', 
                          logs=logs,
                          users=users,
                          actions=actions,
                          filters={
                              'user_id': user_id,
                              'action': action,
                              'date_from': date_from,
                              'date_to': date_to
                          })

@admin.route('/get_delivery_companies')
def get_delivery_companies():
    """Get all delivery companies from the database (both active and inactive for admin)"""
    try:
        # For admin, show companies from their branch only (active and inactive)
        companies = filter_by_user_branch(
            DeliveryCompany.query.order_by(DeliveryCompany.name), 
            DeliveryCompany
        ).all()

        # If no companies exist yet for this branch, auto-seed defaults for first-time setup
        if not companies:
            branch_id = current_user.branch_id
            if branch_id:
                defaults = [
                    { 'name': 'Delivaroo', 'value': 'delivaroo',  'icon': 'bi-bicycle' },
                    { 'name': 'Talabat',   'value': 'talabat',    'icon': 'bi-truck'   },
                    { 'name': 'Rafiq',     'value': 'rafiq',      'icon': 'bi-car'     },
                    { 'name': 'Snounou',   'value': 'snounou',    'icon': 'bi-scooter' }
                ]
                # Avoid duplicates in rare race conditions
                existing_values = set(
                    v.value for v in DeliveryCompany.query.filter_by(branch_id=branch_id).all()
                )
                created_any = False
                for d in defaults:
                    if d['value'] not in existing_values:
                        company = DeliveryCompany(
                            name=d['name'],
                            value=d['value'],
                            icon=d['icon'],
                            branch_id=branch_id,
                            is_active=True
                        )
                        db.session.add(company)
                        created_any = True
                if created_any:
                    db.session.commit()
                # Reload list
                companies = filter_by_user_branch(
                    DeliveryCompany.query.order_by(DeliveryCompany.name),
                    DeliveryCompany
                ).all()
        # Normalize icons for existing records if missing/invalid
        icon_defaults = {
            'talabat': 'bi-truck',
            'delivaroo': 'bi-bicycle',
            'rafiq': 'bi-car',
            'snounou': 'bi-scooter',
        }
        changed = False
        for company in companies:
            icon_val = (company.icon or '').strip() if company.icon is not None else ''
            # Decide if icon needs normalization
            needs_icon = (not icon_val) or (not any(part.startswith('bi-') for part in icon_val.split()))
            if needs_icon:
                # Pick default based on value; fallback to truck
                default_icon = icon_defaults.get((company.value or '').lower(), 'bi-truck')
                company.icon = default_icon
                changed = True
        if changed:
            db.session.commit()
            # Reload companies to ensure fresh state
            companies = filter_by_user_branch(
                DeliveryCompany.query.order_by(DeliveryCompany.name),
                DeliveryCompany
            ).all()

        companies_data = [company.to_dict() for company in companies]
        
        return jsonify({
            'success': True,
            'companies': companies_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })

@admin.route('/add_delivery_company', methods=['POST'])
def add_delivery_company():
    """Add a new delivery company to the database"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        value = data.get('value', '').strip().lower()
        icon = data.get('icon', 'bi-truck').strip()
        branch_id = current_user.branch_id
        if not branch_id:
            return jsonify({
                'success': False,
                'message': 'User is not assigned to a branch. Cannot add company.'
            }), 400
        
        if not name or not value:
            return jsonify({
                'success': False,
                'message': 'Name and value are required'
            })
        
        # Validate value format
        if not value.replace('_', '').isalpha():
            return jsonify({
                'success': False,
                'message': 'Value must contain only letters and underscores'
            })
        
        # Check if value already exists in THIS branch only
        existing_company = DeliveryCompany.query.filter_by(value=value, branch_id=branch_id).first()
        if existing_company:
            return jsonify({
                'success': False,
                'message': 'A company with this value already exists'
            })
        
        # Create new delivery company
        # Normalize icon to a 'bi-*' class if needed (model to_dict will add base 'bi')
        if icon and not any(part.startswith('bi-') for part in icon.split()):
            icon = f'bi-{icon}'
        new_company = DeliveryCompany(
            name=name,
            value=value,
            icon=icon,
            branch_id=branch_id,
            is_active=True
        )
        
        db.session.add(new_company)
        
        # Log the action
        log_entry = AuditLog(
            user_id=current_user.id,
            action='ADD_DELIVERY_COMPANY',
            description=f'Added delivery company: {name} ({value}) with icon {icon}'
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Delivery company "{name}" added successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        })

@admin.route('/toggle_delivery_company', methods=['POST'])
def toggle_delivery_company():
    """Toggle delivery company active/inactive status"""
    try:
        data = request.get_json()
        value = data.get('value', '').strip()
        is_active = data.get('is_active', True)
        branch_id = current_user.branch_id
        
        if not value:
            return jsonify({
                'success': False,
                'message': 'Company value is required'
            })
        
        # Find the company
        company = DeliveryCompany.query.filter_by(value=value, branch_id=branch_id).first()
        if not company:
            return jsonify({
                'success': False,
                'message': 'Delivery company not found'
            })
        
        # Update active status
        old_status = company.is_active
        company.is_active = is_active
        
        # Log the action
        action_text = 'activated' if is_active else 'deactivated'
        log_entry = AuditLog(
            user_id=current_user.id,
            action='TOGGLE_DELIVERY_COMPANY',
            description=f'{action_text.title()} delivery company: {company.name} ({value})'
        )
        db.session.add(log_entry)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Delivery company "{company.name}" {action_text} successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        })

@admin.route('/update_delivery_company_icon', methods=['POST'])
def update_delivery_company_icon():
    """Update only the icon for a delivery company in the current branch."""
    try:
        data = request.get_json()
        value = (data.get('value') or '').strip()
        icon = (data.get('icon') or '').strip()
        branch_id = current_user.branch_id

        if not branch_id:
            return jsonify({'success': False, 'message': 'User is not assigned to a branch'}), 400
        if not value:
            return jsonify({'success': False, 'message': 'Company value is required'}), 400
        if not icon:
            return jsonify({'success': False, 'message': 'Icon is required'}), 400

        # Normalize icon to a single bi-* class (model serializer will add base 'bi')
        # Accept either 'bi-xxx' or raw 'xxx'
        icon_parts = icon.split()
        bi_icon = None
        for p in icon_parts:
            if p.startswith('bi-'):
                bi_icon = p
                break
        if not bi_icon:
            bi_icon = f'bi-{icon}' if not icon.startswith('bi-') else icon

        company = DeliveryCompany.query.filter_by(value=value, branch_id=branch_id).first()
        if not company:
            return jsonify({'success': False, 'message': 'Delivery company not found in this branch'}), 404

        company.icon = bi_icon

        # Audit log
        log_entry = AuditLog(
            user_id=current_user.id,
            action='UPDATE_DELIVERY_COMPANY_ICON',
            description=f'Updated icon for {company.name} ({company.value}) to {bi_icon}'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Icon updated successfully', 'company': company.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/cashier_performance')
def cashier_performance():
    # Get cashiers from current user's branch only
    cashiers = filter_by_user_branch(
        User.query.filter_by(role=UserRole.CASHIER), 
        User
    ).all()
    
    # Get date range from request or default to last 7 days
    days = request.args.get('days', 7, type=int)
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')
    
    if custom_start and custom_end:
        start_date = datetime.strptime(custom_start, '%Y-%m-%d')
        end_date = datetime.strptime(custom_end, '%Y-%m-%d') + timedelta(days=1)  # Include the end date
    else:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
    
    # Prepare performance data for each cashier
    performance_data = []
    
    for cashier in cashiers:
        # Count orders specific to this cashier only (branch-filtered)
        # This includes:
        # 1. Orders created directly by this cashier (both PAID and PENDING)
        # 2. Waiter orders that this cashier marked as PAID (processed by this cashier)
        
        # Get orders created by this cashier
        cashier_orders_query = Order.query.filter(
            and_(
                Order.cashier_id == cashier.id,
                Order.created_at >= start_date,
                Order.created_at <= end_date,
                Order.branch_id == current_user.branch_id  # Branch filtering
            )
        )
        cashier_orders = cashier_orders_query.all()
        
        # Get waiter orders assigned to this cashier (branch-filtered)
        assigned_waiter_orders_query = Order.query.filter(
            and_(
                Order.assigned_cashier_id == cashier.id,
                Order.created_at >= start_date,
                Order.created_at <= end_date,
                Order.branch_id == current_user.branch_id  # Branch filtering
            )
        )
        assigned_waiter_orders = assigned_waiter_orders_query.all()
        
        # Combine cashier's own orders with waiter orders assigned to them
        all_orders = cashier_orders + assigned_waiter_orders
        
        # Count ALL orders (cashier's own + waiter orders they processed)
        orders_count = len(all_orders)
        
        # Count only revenue from PAID orders
        paid_orders = [order for order in all_orders if hasattr(order, 'status') and order.status == OrderStatus.PAID]
        order_revenue = sum(order.total_amount for order in paid_orders)
        
        # Get manual card payments for this cashier in the date range
        manual_card_query = ManualCardPayment.query.filter_by(
            cashier_id=cashier.id,
            branch_id=current_user.branch_id
        )
        
        if start_date and end_date:
            manual_card_query = manual_card_query.filter(
                ManualCardPayment.date >= start_date.date(),
                ManualCardPayment.date <= end_date.date()
            )
        
        manual_card_revenue = sum(payment.amount for payment in manual_card_query.all())
        total_sales = order_revenue + manual_card_revenue
        
        # Convert to float to avoid decimal arithmetic issues
        total_sales = float(total_sales)
        order_revenue = float(order_revenue)
        manual_card_revenue = float(manual_card_revenue)
        
        # Get average order value based on PAID orders only
        if len(paid_orders) > 0:
            avg_order_value = total_sales / len(paid_orders)
        else:
            avg_order_value = 0
            
        # Get login count for the period (from audit logs)
        login_count = AuditLog.query.filter(
            and_(
                AuditLog.user_id == cashier.id,
                AuditLog.action == 'login',
                AuditLog.created_at >= start_date,
                AuditLog.created_at <= end_date
            )
        ).count()
        
        # Count paid and unpaid orders separately
        unpaid_orders = [order for order in all_orders if hasattr(order, 'status') and order.status == OrderStatus.PENDING]
        paid_orders_count = len(paid_orders)
        unpaid_orders_count = len(unpaid_orders)
        
        # Calculate efficiency score (simplified - based on productivity only)
        efficiency_score = min(100.0, float(
            (orders_count * 3) + 
            (total_sales / 100)
        ))
        
        performance_data.append({
            'cashier': cashier,
            'orders_count': orders_count,  # ALL orders (including waiter PENDING orders)
            'paid_orders_count': paid_orders_count,  # Only PAID orders
            'unpaid_orders_count': unpaid_orders_count,  # Only PENDING orders
            'total_sales': total_sales,  # Orders + Manual Card Payments
            'order_revenue': order_revenue,  # Only from PAID orders
            'manual_card_revenue': manual_card_revenue,  # Manual card payments
            'avg_order_value': avg_order_value,
            'login_count': login_count,
            'efficiency_score': efficiency_score,
            'branch': cashier.branch
        })
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        performance_json = []
        for data in performance_data:
            performance_json.append({
                'cashier': {
                    'id': data['cashier'].id,
                    'username': data['cashier'].username,
                    'full_name': data['cashier'].get_full_name()
                },
                'orders_count': data['orders_count'],
                'paid_orders_count': data['paid_orders_count'],
                'unpaid_orders_count': data['unpaid_orders_count'],
                'total_sales': data['total_sales'],
                'order_revenue': data['order_revenue'],
                'manual_card_revenue': data['manual_card_revenue'],
                'avg_order_value': data['avg_order_value'],
                'login_count': data['login_count'],
                'efficiency_score': data['efficiency_score']
            })
        
        return jsonify({
            'performance_data': performance_json,
            'days': days,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        })
    
    return render_template('admin/cashier_performance.html', 
                          performance_data=performance_data,
                          days=days,
                          start_date=start_date,
                          end_date=end_date)

@admin.route('/add_to_quick_category', methods=['POST'])
def add_to_quick_category():
    """Add selected items to Quick category"""
    try:
        data = request.get_json()
        item_ids = data.get('item_ids', [])
        branch_id = current_user.branch_id
        
        if not item_ids:
            return jsonify({'success': False, 'message': 'No items selected'})
        
        # Get the Quick category
        quick_category = Category.query.filter_by(name='Quick', branch_id=branch_id).first()
        if not quick_category:
            return jsonify({'success': False, 'message': 'Quick category not found'})
        
        added_count = 0
        
        for item_id in item_ids:
            # Get the original item
            original_item = MenuItem.query.get(item_id)
            if not original_item:
                continue
            # Only allow adding items from the same branch
            if original_item.branch_id != branch_id:
                continue
                
            # Check if item is already in Quick category
            existing_quick_item = MenuItem.query.filter_by(
                name=original_item.name,
                category_id=quick_category.id,
                original_category_id=original_item.category_id
            ).first()
            
            if existing_quick_item:
                continue  # Skip if already exists
            
            # Create a new item in Quick category
            quick_item = MenuItem(
                name=original_item.name,
                price=original_item.price,
                description=original_item.description,
                image_url=original_item.image_url,
                category_id=quick_category.id,
                original_category_id=original_item.category_id,
                branch_id=branch_id,
                is_active=original_item.is_active,
                is_vegetarian=original_item.is_vegetarian,
                is_vegan=original_item.is_vegan,
                card_color=original_item.card_color,
                size_flag=original_item.size_flag,
                portion_type=original_item.portion_type,
                visual_priority=original_item.visual_priority
            )
            
            db.session.add(quick_item)
            added_count += 1
        
        db.session.commit()
        
        # Log the action
        log = AuditLog(
            user_id=current_user.id,
            action=f'Added {added_count} items to Quick category',
            description=f'Added {added_count} menu items to Quick category for fast access'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully added {added_count} items to Quick category',
            'added_count': added_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/remove_from_quick_category', methods=['POST'])
def remove_from_quick_category():
    """Remove item from Quick category"""
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        branch_id = current_user.branch_id
        
        if not item_id:
            return jsonify({'success': False, 'message': 'No item ID provided'})
        
        # Get the item
        item = MenuItem.query.get(item_id)
        if not item:
            return jsonify({'success': False, 'message': 'Item not found'})
        # Enforce branch isolation
        if item.branch_id != branch_id:
            return jsonify({'success': False, 'message': 'Access denied for this branch'}), 403
        
        # Check if it's actually in Quick category
        quick_category = Category.query.filter_by(name='Quick', branch_id=branch_id).first()
        if not quick_category or item.category_id != quick_category.id:
            return jsonify({'success': False, 'message': 'Item is not in Quick category'})
        
        # Store item name for logging
        item_name = item.name
        
        # Delete the item from Quick category
        db.session.delete(item)
        db.session.commit()
        
        # Log the action
        log = AuditLog(
            user_id=current_user.id,
            action=f'Removed item "{item_name}" from Quick category',
            description=f'Removed menu item "{item_name}" from Quick category'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully removed "{item_name}" from Quick category'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/get_quick_category_data', methods=['GET'])
def get_quick_category_data():
    """Get data for Quick category management"""
    try:
        branch_id = current_user.branch_id
        # Get the Quick category
        quick_category = Category.query.filter_by(name='Quick', branch_id=branch_id).first()
        if not quick_category:
            return jsonify({'success': False, 'message': 'Quick category not found'})
        
        # Get available items (not in Quick category)
        # Explicitly specify the join condition to avoid ambiguity
        available_items_query = db.session.query(MenuItem).join(
            Category, MenuItem.category_id == Category.id
        ).filter(
            MenuItem.branch_id == branch_id,
            Category.branch_id == branch_id,
            Category.name.notin_(['Quick', 'طلبات خاصة']),
            MenuItem.is_active == True
        ).order_by(Category.name, MenuItem.name)
        
        available_items = []
        try:
            for item in available_items_query:
                available_items.append({
                    'id': item.id,
                    'name': item.name,
                    'price': float(item.price),
                    'category_name': item.category.name
                })
        except Exception as e:
            # If there are no items or query fails, just return empty list
            print(f"No available items found: {e}")
        
        # Get quick items
        quick_items_query = MenuItem.query.filter_by(category_id=quick_category.id, branch_id=branch_id).order_by(MenuItem.name)
        
        quick_items = []
        try:
            for item in quick_items_query:
                quick_items.append({
                    'id': item.id,
                    'name': item.name,
                    'price': float(item.price),
                    'original_category_name': item.original_category.name if item.original_category else None
                })
        except Exception as e:
            # If there are no quick items or query fails, just return empty list
            print(f"No quick items found: {e}")

        # If Quick category is empty for this branch, auto-populate with all current available items
        if len(quick_items) == 0 and len(available_items) > 0:
            created = 0
            for item in db.session.query(MenuItem).join(Category, MenuItem.category_id == Category.id).filter(
                MenuItem.branch_id == branch_id,
                Category.branch_id == branch_id,
                Category.name.notin_(['Quick', 'طلبات خاصة']),
                MenuItem.is_active == True
            ).all():
                # Ensure not already in Quick (fresh branch usually isn't)
                new_q = MenuItem(
                    name=item.name,
                    price=item.price,
                    description=item.description,
                    image_url=item.image_url,
                    category_id=quick_category.id,
                    original_category_id=item.category_id,
                    branch_id=branch_id,
                    is_active=item.is_active,
                    is_vegetarian=item.is_vegetarian,
                    is_vegan=item.is_vegan,
                    card_color=item.card_color,
                    size_flag=item.size_flag,
                    portion_type=item.portion_type,
                    visual_priority=item.visual_priority
                )
                db.session.add(new_q)
                created += 1
            if created:
                db.session.commit()
                # Reload quick items list after seeding
                quick_items = []
                for item in MenuItem.query.filter_by(category_id=quick_category.id, branch_id=branch_id).order_by(MenuItem.name):
                    quick_items.append({
                        'id': item.id,
                        'name': item.name,
                        'price': float(item.price),
                        'original_category_name': item.original_category.name if item.original_category else None
                    })
        
        return jsonify({
            'success': True,
            'available_items': available_items,
            'quick_items': quick_items
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/get_tables_data', methods=['GET'])
def get_tables_data():
    """Get data for table management"""
    try:
        from app.models import Table
        
        # Get tables from current user's branch only
        tables_query = filter_by_user_branch(
            Table.query.order_by(Table.table_number), 
            Table
        )
        
        tables = []
        for table in tables_query:
            tables.append({
                'id': table.id,
                'table_number': table.table_number,
                'capacity': table.capacity,
                'description': getattr(table, 'description', None) or '',
                'is_active': table.is_active
            })
        
        return jsonify({
            'success': True,
            'tables': tables
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/create_table', methods=['POST'])
def create_table():
    """Create a new table"""
    try:
        from app.models import Table
        
        data = request.get_json()
        table_number = data.get('table_number', '').strip()
        capacity = data.get('capacity')
        description = data.get('description', '').strip()
        
        if not table_number or not capacity:
            return jsonify({'success': False, 'message': 'Table number and capacity are required'})
        
        # Check if table number already exists in the same branch
        existing_table = filter_by_user_branch(
            Table.query.filter_by(table_number=table_number), 
            Table
        ).first()
        if existing_table:
            return jsonify({'success': False, 'message': f'Table "{table_number}" already exists in this branch'})
        
        # Create new table with branch assignment
        new_table = Table(
            table_number=table_number,
            capacity=capacity,
            description=description if description else None,
            is_active=True,
            branch_id=current_user.branch_id
        )
        
        db.session.add(new_table)
        db.session.commit()
        
        # Log the action
        log = AuditLog(
            user_id=current_user.id,
            action=f'Created table "{table_number}"',
            description=f'Added new table with {capacity} seats'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Table "{table_number}" created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/update_table/<int:table_id>', methods=['POST'])
def update_table(table_id):
    """Update an existing table"""
    try:
        from app.models import Table
        
        table = Table.query.get(table_id)
        if not table:
            return jsonify({'success': False, 'message': 'Table not found'})
        
        data = request.get_json()
        table_number = data.get('table_number', '').strip()
        capacity = data.get('capacity')
        description = data.get('description', '').strip()
        is_active = data.get('is_active', True)
        
        if not table_number or not capacity:
            return jsonify({'success': False, 'message': 'Table number and capacity are required'})
        
        # Check if table number already exists (excluding current table)
        existing_table = Table.query.filter(
            Table.table_number == table_number,
            Table.id != table_id
        ).first()
        if existing_table:
            return jsonify({'success': False, 'message': f'Table "{table_number}" already exists'})
        
        # Store old values for logging
        old_table_number = table.table_number
        
        # Update table
        table.table_number = table_number
        table.capacity = capacity
        table.description = description if description else None
        table.is_active = is_active
        
        db.session.commit()
        
        # Log the action
        log = AuditLog(
            user_id=current_user.id,
            action=f'Updated table "{old_table_number}"',
            description=f'Updated table details (now "{table_number}" with {capacity} seats)'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Table "{table_number}" updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/delete_table/<int:table_id>', methods=['DELETE'])
def delete_table(table_id):
    """Delete a table"""
    try:
        from app.models import Table
        
        table = Table.query.get(table_id)
        if not table:
            return jsonify({'success': False, 'message': 'Table not found'})
        
        # Store table info for logging
        table_number = table.table_number
        
        # Delete the table
        db.session.delete(table)
        db.session.commit()
        
        # Log the action
        log = AuditLog(
            user_id=current_user.id,
            action=f'Deleted table "{table_number}"',
            description=f'Removed table "{table_number}" from the system'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Table "{table_number}" deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin.route('/get_order_details/<int:order_id>')
@login_required
def get_order_details(order_id):
    """Get order details for admin - same as POS but admin-specific"""
    try:
        order = Order.query.get_or_404(order_id)
        
        items = []
        for item in order.order_items:
            items.append({
                'id': item.id,
                'menu_item_name': item.menu_item.name,  # Frontend expects menu_item_name
                'name': item.menu_item.name,  # Keep for backward compatibility
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total_price': float(item.total_price),
                'special_requests': item.special_requests or item.notes,  # Include special requests
                'modifiers': item.notes,  # Include modifiers from notes field
                'is_new': item.is_new or False,  # Edit tracking
                'is_deleted': item.is_deleted or False  # Edit tracking
            })
        
        # Get delivery company name safely
        delivery_company_name = None
        if order.delivery_company_id and order.delivery_company_info:
            delivery_company_name = order.delivery_company_info.name
        
        return jsonify({
            'success': True,
            'id': order.id,
            'order_number': order.order_number,
            'order_counter': order.order_counter if order.order_counter else None,
            'total_amount': float(order.total_amount),
            'created_at': TimezoneManager.format_local_time(order.created_at, '%Y-%m-%d %H:%M:%S'),
            'table_number': order.table.table_number if order.table else None,
            'cashier_name': order.cashier.get_full_name() if order.cashier else None,
            'service_type': order.service_type.value if order.service_type else 'on_table',
            'delivery_company': delivery_company_name,
            'edit_count': order.edit_count or 0,
            'last_edited_at': TimezoneManager.format_local_time(order.last_edited_at, '%Y-%m-%d %H:%M:%S') if order.last_edited_at else None,
            'last_edited_by': User.query.get(order.last_edited_by).get_full_name() if order.last_edited_by else None,
            'items': items
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error loading order details: {str(e)}'
        }), 500

@admin.route('/reports')
def reports():
    """Advanced reports page with interactive graphs - branch-specific data"""
    
    # Build base query for current admin's branch only
    base_query = Order.query.filter(Order.branch_id == current_user.branch_id)
    
    # Get statistics (branch-specific) - separate paid and unpaid
    total_orders = base_query.count()  # ALL orders (including PENDING)
    total_paid_orders = base_query.filter(Order.status == OrderStatus.PAID).count()
    total_unpaid_orders = base_query.filter(Order.status == OrderStatus.PENDING).count()
    
    # Revenue only from PAID orders
    total_revenue_query = db.session.query(func.sum(Order.total_amount)).filter(
        Order.status == OrderStatus.PAID,
        Order.branch_id == current_user.branch_id
    )
    total_revenue = total_revenue_query.scalar() or 0
    
    # Average order value - calculated from PAID orders only
    avg_order_value = (total_revenue / total_paid_orders) if total_paid_orders > 0 else 0
    
    # Today's statistics - separate paid and unpaid
    today = datetime.utcnow().date()
    today_query = base_query.filter(func.date(Order.created_at) == today)
    today_orders = today_query.count()
    today_paid_orders = today_query.filter(Order.status == OrderStatus.PAID).count()
    today_unpaid_orders = today_query.filter(Order.status == OrderStatus.PENDING).count()
    
    # Today's revenue only from PAID orders
    today_revenue_query = db.session.query(func.sum(Order.total_amount)).filter(
        func.date(Order.created_at) == today,
        Order.status == OrderStatus.PAID,
        Order.branch_id == current_user.branch_id
    )
    today_revenue = today_revenue_query.scalar() or 0
    
    # Sales trend for last 30 days
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)
    
    from sqlalchemy import case
    daily_sales_query = db.session.query(
        func.date(Order.created_at).label('date'),
        func.sum(case((Order.status == OrderStatus.PAID, Order.total_amount), else_=0)).label('total'),
        func.count(Order.id).label('total_orders'),
        func.sum(case((Order.status == OrderStatus.PAID, 1), else_=0)).label('paid_orders'),
        func.sum(case((Order.status == OrderStatus.PENDING, 1), else_=0)).label('unpaid_orders')
    ).filter(
        Order.created_at >= start_date,
        Order.branch_id == current_user.branch_id
    )
    
    daily_sales = daily_sales_query.group_by(
        func.date(Order.created_at)
    ).order_by(
        func.date(Order.created_at)
    ).all()
    
    # Top performing items (branch-specific) - only from PAID orders
    top_items_query = db.session.query(
        MenuItem.name,
        func.sum(OrderItem.quantity).label('total_quantity'),
        func.sum(OrderItem.total_price).label('total_revenue')
    ).join(OrderItem, MenuItem.id == OrderItem.menu_item_id)\
     .join(Order, OrderItem.order_id == Order.id)\
     .filter(
         Order.created_at >= start_date,
         Order.status == OrderStatus.PAID,
         Order.branch_id == current_user.branch_id
     )
    
    top_items = top_items_query.group_by(MenuItem.id, MenuItem.name)\
     .order_by(func.sum(OrderItem.quantity).desc())\
     .limit(20).all()
    
    # Get service type distribution for pie chart - only from PAID orders
    from app.models import ServiceType
    service_type_stats = db.session.query(
        Order.service_type,
        func.count(Order.id).label('count'),
        func.sum(Order.total_amount).label('revenue')
    ).filter(
        Order.created_at >= start_date,
        Order.status == OrderStatus.PAID,
        Order.branch_id == current_user.branch_id
    ).group_by(Order.service_type).all()
    
    # Format service type data for the template
    service_type_data = {
        'on_table': {'count': 0, 'revenue': 0},
        'take_away': {'count': 0, 'revenue': 0},
        'delivery': {'count': 0, 'revenue': 0},
        'card': {'count': 0, 'revenue': 0}
    }
    
    for stat in service_type_stats:
        if stat.service_type == ServiceType.ON_TABLE:
            service_type_data['on_table'] = {'count': stat.count, 'revenue': float(stat.revenue or 0)}
        elif stat.service_type == ServiceType.TAKE_AWAY:
            service_type_data['take_away'] = {'count': stat.count, 'revenue': float(stat.revenue or 0)}
        elif stat.service_type == ServiceType.DELIVERY:
            service_type_data['delivery'] = {'count': stat.count, 'revenue': float(stat.revenue or 0)}
        elif stat.service_type == ServiceType.CARD:
            service_type_data['card'] = {'count': stat.count, 'revenue': float(stat.revenue or 0)}
    
    # Get delivery companies for filtering (branch-specific)
    delivery_companies = filter_by_user_branch(
        DeliveryCompany.query.filter_by(is_active=True), 
        DeliveryCompany
    ).all()
    
    return render_template('admin/reports.html',
                         total_orders=total_orders,
                         total_paid_orders=total_paid_orders,
                         total_unpaid_orders=total_unpaid_orders,
                         total_revenue=total_revenue,
                         avg_order_value=avg_order_value,
                         today_orders=today_orders,
                         today_paid_orders=today_paid_orders,
                         today_unpaid_orders=today_unpaid_orders,
                         today_revenue=today_revenue,
                         daily_sales=daily_sales,
                         top_items=top_items,
                         service_type_data=service_type_data,
                         delivery_companies=delivery_companies,
                         title='Advanced Reports')

@admin.route('/api/reports/revenue-orders')
@login_required
def api_revenue_orders():
    """
    API endpoint for revenue and orders data - branch-specific
    
    Manual Card Payment Integration:
    - Included in: "Revenue & Orders Over Time" (service_type='all') and "Card Payments Analysis" (service_type='card')
    - Excluded from: "Take Away Orders", "Delivery Orders", "On Table Orders" graphs
    """
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        service_type = request.args.get('service_type')
        delivery_company_id = request.args.get('delivery_company_id')
        branch_id = request.args.get('branch_id')
        time_period = request.args.get('time_period', '7')  # Default 7 days
        
        # Calculate date range based on time_period if no specific dates provided
        if not date_from or not date_to:
            end_date = datetime.utcnow()
            
            try:
                days = int(time_period)
                start_date = end_date - timedelta(days=days)
            except (ValueError, TypeError):
                # Default to 7 days if time_period is invalid
                start_date = end_date - timedelta(days=7)
        else:
            try:
                start_date = datetime.strptime(date_from, '%Y-%m-%d')
                end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            except ValueError as e:
                return jsonify({'success': False, 'error': f'Invalid date format: {str(e)}'}), 400
        
        # Build base query with branch filtering
        query = filter_by_user_branch(
            Order.query.filter(
                Order.created_at >= start_date,
                Order.created_at <= end_date
            ), 
            Order
        )
        
        # Apply superuser branch filter if specified
        if branch_id and branch_id != 'all' and current_user.is_super_user():
            try:
                branch_id_int = int(branch_id)
                query = query.filter(Order.branch_id == branch_id_int)
            except (ValueError, TypeError):
                pass
        
        # Apply service type filter
        if service_type and service_type != 'all':
            if service_type == 'delivery':
                query = query.filter(Order.service_type == ServiceType.DELIVERY)
            elif service_type == 'on_table':
                query = query.filter(Order.service_type == ServiceType.ON_TABLE)
            elif service_type == 'take_away':
                query = query.filter(Order.service_type == ServiceType.TAKE_AWAY)
            elif service_type == 'card':
                # For card service type, we only want manual card payments, not orders
                query = query.filter(Order.id == -1)  # This will return no orders
        
        # Apply delivery company filter
        if delivery_company_id and delivery_company_id != 'all':
            query = query.filter(Order.delivery_company_id == int(delivery_company_id))
        
        # Get orders and group by date
        orders = query.all()
        
        # Group data by date - separate order counts and revenue by payment status
        daily_data = {}
        total_paid_orders = 0
        for order in orders:
            date_key = order.created_at.strftime('%Y-%m-%d')
            if date_key not in daily_data:
                daily_data[date_key] = {
                    'revenue': 0,
                    'orders': 0,
                    'paid_orders': 0,
                    'date': date_key
                }
            # Count ALL orders (including PENDING)
            daily_data[date_key]['orders'] += 1
            
            # Only count revenue from PAID orders
            if hasattr(order, 'status') and order.status == OrderStatus.PAID:
                daily_data[date_key]['revenue'] += float(order.total_amount)
                daily_data[date_key]['paid_orders'] += 1
                total_paid_orders += 1
        
        # Add manual card payments to daily data ONLY for:
        # 1. "Revenue & Orders Over Time" (service_type == 'all' or None)
        # 2. "Card Payments Analysis" (service_type == 'card')
        # DO NOT include for specific service types: delivery, take_away, on_table
        if not service_type or service_type == 'all' or service_type == 'card':
            manual_card_query = ManualCardPayment.query.filter(
                ManualCardPayment.date >= start_date.date(),
                ManualCardPayment.date <= end_date.date()
            )
            
            # Apply branch filtering for manual card payments
            if branch_id and branch_id != 'all' and current_user.is_super_user():
                try:
                    branch_id_int = int(branch_id)
                    manual_card_query = manual_card_query.filter(ManualCardPayment.branch_id == branch_id_int)
                except (ValueError, TypeError):
                    pass
            elif current_user.role == UserRole.BRANCH_ADMIN:
                manual_card_query = manual_card_query.filter(ManualCardPayment.branch_id == current_user.branch_id)
            
            manual_card_payments = manual_card_query.all()
            
            for payment in manual_card_payments:
                date_key = payment.date.strftime('%Y-%m-%d')
                if date_key not in daily_data:
                    daily_data[date_key] = {
                        'revenue': 0,
                        'orders': 0,
                        'paid_orders': 0,
                        'date': date_key
                    }
                daily_data[date_key]['revenue'] += float(payment.amount)
        
        # Convert to list and sort by date
        result = list(daily_data.values())
        result.sort(key=lambda x: x['date'])
        
        return jsonify({
            'success': True,
            'data': result,
            'summary': {
                'total_revenue': sum(item['revenue'] for item in result),
                'total_orders': sum(item['orders'] for item in result),
                'total_paid_orders': total_paid_orders,
                'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            }
        })
        
    except Exception as e:
        print(f"Error in revenue-orders API: {str(e)}")
        print(f"Parameters: time_period={time_period}, service_type={service_type}, delivery_company_id={delivery_company_id}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin.route('/api/reports/delivery-companies')
@login_required
def api_delivery_companies_data():
    """API endpoint for delivery companies performance data"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        time_period = request.args.get('time_period', '7')
        service_type = request.args.get('service_type', 'all')
        delivery_company_id = request.args.get('delivery_company_id', 'all')
        
        print(f"Delivery companies API called with: time_period={time_period}, service_type={service_type}, delivery_company_id={delivery_company_id}")
        
        # Calculate date range
        if not date_from or not date_to:
            end_date = datetime.utcnow()
            days = int(time_period) if time_period.isdigit() else 7
            start_date = end_date - timedelta(days=days)
        else:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        
        # Build query for orders with branch filtering
        query = filter_by_user_branch(
            Order.query.filter(
                Order.created_at >= start_date,
                Order.created_at <= end_date
            ),
            Order
        )
        
        # Apply service type filter
        if service_type != 'all':
            if service_type == 'delivery':
                query = query.filter(Order.service_type == ServiceType.DELIVERY)
            elif service_type == 'take_away':
                query = query.filter(Order.service_type == ServiceType.TAKE_AWAY)
            elif service_type == 'on_table':
                query = query.filter(Order.service_type == ServiceType.ON_TABLE)
        
        # For delivery company analysis, we only want delivery orders
        if service_type == 'all' or service_type == 'delivery':
            query = query.filter(
                Order.service_type == ServiceType.DELIVERY,
                Order.delivery_company_id.isnot(None)
            )
            
            # Apply delivery company filter
            if delivery_company_id != 'all':
                try:
                    company_id = int(delivery_company_id)
                    query = query.filter(Order.delivery_company_id == company_id)
                except ValueError:
                    pass
        else:
            # If not delivery service, return empty data
            return jsonify({
                'success': True,
                'data': {},
                'companies_performance': [],
                'date_ranges': [],
                'summary': {
                    'total_orders': 0,
                    'total_revenue': 0,
                    'average_order_value': 0,
                    'active_companies': 0
                }
            })
        
        orders = query.all()
        print(f"Found {len(orders)} delivery orders")
        
        # Group by delivery company and date
        company_data = {}
        total_orders = 0
        total_revenue = 0
        active_companies = set()
        
        for order in orders:
            if not order.delivery_company_info:
                continue
                
            company_name = order.delivery_company_info.name
            company_id = order.delivery_company_info.id
            date_key = order.created_at.strftime('%Y-%m-%d')
            
            active_companies.add(company_id)
            total_orders += 1
            total_revenue += float(order.total_amount)
            
            if company_name not in company_data:
                company_data[company_name] = {}
            
            if date_key not in company_data[company_name]:
                company_data[company_name][date_key] = {
                    'revenue': 0,
                    'orders': 0,
                    'date': date_key
                }
            
            company_data[company_name][date_key]['revenue'] += float(order.total_amount)
            company_data[company_name][date_key]['orders'] += 1
        
        # Format for chart
        result = {}
        companies_performance = []
        
        for company, dates in company_data.items():
            result[company] = list(dates.values())
            result[company].sort(key=lambda x: x['date'])
            
            # Calculate company totals
            company_orders = sum(d['orders'] for d in result[company])
            company_revenue = sum(d['revenue'] for d in result[company])
            
            companies_performance.append({
                'company': company,
                'orders': company_orders,
                'revenue': company_revenue,
                'average_order_value': company_revenue / company_orders if company_orders > 0 else 0
            })
        
        # Generate date ranges for the chart
        date_ranges = []
        current_date = start_date
        while current_date < end_date:
            date_ranges.append(current_date.strftime('%Y-%m-%d'))
            current_date += timedelta(days=1)
        
        return jsonify({
            'success': True,
            'data': result,
            'companies_performance': companies_performance,
            'date_ranges': date_ranges,
            'summary': {
                'total_orders': total_orders,
                'total_revenue': total_revenue,
                'average_order_value': total_revenue / total_orders if total_orders > 0 else 0,
                'active_companies': len(active_companies)
            }
        })
        
    except Exception as e:
        print(f"Error in delivery companies API: {str(e)}")
        print(f"Parameters: time_period={time_period}, service_type={service_type}, delivery_company_id={delivery_company_id}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin.route('/api/reports/service-type-breakdown')
@login_required
def api_service_type_breakdown():
    """API endpoint for service type breakdown data"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        time_period = request.args.get('time_period', '7')
        
        # Calculate date range
        if not date_from or not date_to:
            end_date = datetime.utcnow()
            days = int(time_period) if time_period.isdigit() else 7
            start_date = end_date - timedelta(days=days)
        else:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        
        # Get orders in date range with branch filtering
        orders = filter_by_user_branch(
            Order.query.filter(
                Order.created_at >= start_date,
                Order.created_at <= end_date
            ),
            Order
        ).all()
        
        # Debug: Check what service types exist in database
        print(f"Date range: {start_date} to {end_date}")
        print(f"Total orders found: {len(orders)}")
        
        # Check actual service types in the orders
        actual_service_types = set()
        for order in orders:
            if order.service_type:
                actual_service_types.add(order.service_type.value)
                print(f"Order {order.id}: service_type = {order.service_type.value}, amount = {order.total_amount}")
            else:
                actual_service_types.add('None')
                print(f"Order {order.id}: service_type = None, amount = {order.total_amount}")
        
        print(f"Actual service types in database: {actual_service_types}")
        
        # Count by service type (using lowercase to match database values)
        service_type_counts = {
            'on_table': 0,
            'take_away': 0,
            'delivery': 0,
            'card': 0
        }
        
        service_type_revenue = {
            'on_table': 0,
            'take_away': 0,
            'delivery': 0,
            'card': 0
        }
        
        for order in orders:
            service_type = order.service_type.value if order.service_type else 'on_table'
            print(f"Processing order {order.id}: service_type = '{service_type}'")
            if service_type in service_type_counts:
                service_type_counts[service_type] += 1
                service_type_revenue[service_type] += float(order.total_amount)
            else:
                print(f"WARNING: Unknown service type '{service_type}' for order {order.id}")
        
        # Debug output
        print(f"Final service type counts: {service_type_counts}")
        print(f"Final service type revenue: {service_type_revenue}")
        
        # Calculate percentages
        total_orders = sum(service_type_counts.values())
        total_revenue = sum(service_type_revenue.values())
        
        result = {}
        for service_type in service_type_counts:
            result[service_type] = {
                'orders': service_type_counts[service_type],
                'revenue': service_type_revenue[service_type],
                'order_percentage': (service_type_counts[service_type] / total_orders * 100) if total_orders > 0 else 0,
                'revenue_percentage': (service_type_revenue[service_type] / total_revenue * 100) if total_revenue > 0 else 0
            }
        
        return jsonify({
            'success': True,
            'data': result,
            'totals': {
                'orders': total_orders,
                'revenue': total_revenue
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@admin.route('/api/reports/test')
@login_required
def api_test():
    """Simple test endpoint to check if basic functionality works"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get last 7 days of orders
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        orders = Order.query.filter(
            Order.created_at >= start_date,
            Order.created_at <= end_date
        ).all()
        
        return jsonify({
            'success': True,
            'message': 'Test endpoint working',
            'orders_count': len(orders),
            'date_range': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@admin.route('/api/reports/service-type-data')
@login_required
def api_service_type_data():
    """API endpoint for service type distribution data - supports branch filtering"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        time_period = request.args.get('time_period', '7')
        branch_id = request.args.get('branch_id')
        
        # Calculate date range
        if not date_from or not date_to:
            end_date = datetime.utcnow()
            days = int(time_period) if time_period.isdigit() else 7
            start_date = end_date - timedelta(days=days)
        else:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        
        # Build query for service type statistics
        from app.models import ServiceType
        query = db.session.query(
            Order.service_type,
            func.count(Order.id).label('count'),
            func.sum(Order.total_amount).label('revenue')
        ).filter(Order.created_at >= start_date, Order.created_at <= end_date)
        
        # Apply branch filtering
        if current_user.role == UserRole.BRANCH_ADMIN:
            # Branch admin can only see their own branch
            query = query.filter(Order.branch_id == current_user.branch_id)
        elif current_user.role == UserRole.SUPER_USER and branch_id and branch_id != 'all':
            # Super user can filter by specific branch
            query = query.filter(Order.branch_id == int(branch_id))
        # If no branch filter or 'all', super user sees all branches
        
        service_type_stats = query.group_by(Order.service_type).all()
        
        # Format data for the frontend
        service_type_data = {
            'on_table': 0,
            'take_away': 0,
            'delivery': 0,
            'card': 0
        }
        
        total_orders = 0
        for stat in service_type_stats:
            total_orders += stat.count
            if stat.service_type == ServiceType.ON_TABLE:
                service_type_data['on_table'] = stat.count
            elif stat.service_type == ServiceType.TAKE_AWAY:
                service_type_data['take_away'] = stat.count
            elif stat.service_type == ServiceType.DELIVERY:
                service_type_data['delivery'] = stat.count
            elif stat.service_type == ServiceType.CARD:
                service_type_data['card'] = stat.count
        
        return jsonify({
            'success': True,
            'data': service_type_data,
            'total_orders': total_orders
        })
        
    except Exception as e:
        print(f"Error in service type data API: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@admin.route('/settings')
@login_required
def settings():
    """Admin settings page for order editing PIN management"""
    # Get current order editing PIN record for this branch
    order_editing_pin = AdminPinCode.query.filter_by(
        branch_id=current_user.branch_id,
        pin_type='order_editing',
        is_active=True
    ).first()
    
    return render_template('admin/settings.html', 
                         order_editing_pin=order_editing_pin)

@admin.route('/save_pin_settings', methods=['POST'])
@login_required
def save_pin_settings():
    """Save admin order editing PIN"""
    try:
        data = request.get_json()
        order_editing_pin = data.get('order_editing_pin', '').strip()
        
        # Validate order editing PIN code
        if not order_editing_pin or len(order_editing_pin) != 4 or not order_editing_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'Order editing PIN must be exactly 4 digits'
            })
        
        # Check if order editing PIN already exists for this branch
        existing_editing_pin = AdminPinCode.query.filter_by(
            branch_id=current_user.branch_id,
            pin_type='order_editing'
        ).first()
        
        if existing_editing_pin:
            # Update existing PIN
            existing_editing_pin.set_pin(order_editing_pin)
            existing_editing_pin.is_active = True
            existing_editing_pin.updated_at = datetime.utcnow()
        else:
            # Create new order editing PIN (no admin_id needed - one per branch)
            new_editing_pin = AdminPinCode(
                branch_id=current_user.branch_id,
                pin_type='order_editing',
                is_active=True
            )
            new_editing_pin.set_pin(order_editing_pin)
            db.session.add(new_editing_pin)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Order editing PIN saved successfully!'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error saving PIN settings: {str(e)}'
        })

@admin.route('/verify_pin', methods=['POST'])
@login_required
def verify_pin():
    """Verify PIN code (for testing purposes)"""
    try:
        data = request.get_json()
        pin_code = data.get('pin_code', '').strip()
        
        if not pin_code or len(pin_code) != 4 or not pin_code.isdigit():
            return jsonify({
                'success': False,
                'message': 'Invalid PIN code format'
            })
        
        # Verify PIN
        is_valid = AdminPinCode.verify_pin(current_user.branch_id, pin_code)
        
        if not is_valid:
            return jsonify({
                'success': False,
                'message': 'Invalid PIN code'
            })
        
        return jsonify({
            'success': True,
            'message': 'PIN code verified successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error verifying PIN: {str(e)}'
        })

# Order editing PIN routes removed - functionality moved to admin settings page

@admin.route('/api/reports/cash-per-date')
@login_required
def api_cash_per_date():
    """API endpoint for cash per date data - branch-specific"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        time_period = request.args.get('time_period')
        service_type = request.args.get('service_type')
        delivery_company_id = request.args.get('delivery_company_id')
        
        # Handle time period filtering
        if time_period and time_period != 'custom':
            days = int(time_period)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
        elif date_from and date_to:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        else:
            # Default to last 7 days
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=7)
        
        # Build query for cash (order payments only) per date - branch-specific
        from sqlalchemy import case
        cash_per_date_query = db.session.query(
            func.date(Order.created_at).label('date'),
            func.sum(case((Order.status == OrderStatus.PAID, Order.total_amount), else_=0)).label('cash_amount')
        ).filter(
            Order.created_at >= start_date,
            Order.created_at < end_date,
            Order.branch_id == current_user.branch_id  # Branch filtering
        )
        
        # Add service type filtering
        if service_type and service_type != 'all':
            from app.models import ServiceType
            if service_type == 'on_table':
                cash_per_date_query = cash_per_date_query.filter(Order.service_type == ServiceType.ON_TABLE)
            elif service_type == 'take_away':
                cash_per_date_query = cash_per_date_query.filter(Order.service_type == ServiceType.TAKE_AWAY)
            elif service_type == 'delivery':
                cash_per_date_query = cash_per_date_query.filter(Order.service_type == ServiceType.DELIVERY)
        
        # Add delivery company filtering
        if delivery_company_id and delivery_company_id != 'all':
            cash_per_date_query = cash_per_date_query.filter(Order.delivery_company_id == delivery_company_id)
        
        cash_per_date_query = cash_per_date_query.group_by(
            func.date(Order.created_at)
        ).order_by(
            func.date(Order.created_at)
        )
        
        cash_data = cash_per_date_query.all()
        
        # Format data for chart
        result = {
            'dates': [str(item.date) for item in cash_data],
            'cash_amounts': [float(item.cash_amount or 0) for item in cash_data]
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@admin.route('/api/reports/peak-hours')
@login_required
def api_peak_hours():
    """API endpoint for peak selling hours data - branch-specific"""
    if current_user.role not in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'error': 'Access denied'}), 403
    
    try:
        # Get parameters
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        time_period = request.args.get('time_period')
        service_type = request.args.get('service_type')
        delivery_company_id = request.args.get('delivery_company_id')
        
        # Handle time period filtering
        if time_period and time_period != 'custom':
            days = int(time_period)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
        elif date_from and date_to:
            start_date = datetime.strptime(date_from, '%Y-%m-%d')
            end_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        else:
            # Default to last 7 days
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=7)
        
        # Build query for hourly sales data - branch-specific
        from sqlalchemy import case, extract
        hourly_sales_query = db.session.query(
            extract('hour', Order.created_at).label('hour'),
            func.count(Order.id).label('order_count'),
            func.sum(case((Order.status == OrderStatus.PAID, Order.total_amount), else_=0)).label('revenue')
        ).filter(
            Order.created_at >= start_date,
            Order.created_at < end_date,
            Order.branch_id == current_user.branch_id  # Branch filtering
        )
        
        # Add service type filtering
        if service_type and service_type != 'all':
            from app.models import ServiceType
            if service_type == 'on_table':
                hourly_sales_query = hourly_sales_query.filter(Order.service_type == ServiceType.ON_TABLE)
            elif service_type == 'take_away':
                hourly_sales_query = hourly_sales_query.filter(Order.service_type == ServiceType.TAKE_AWAY)
            elif service_type == 'delivery':
                hourly_sales_query = hourly_sales_query.filter(Order.service_type == ServiceType.DELIVERY)
        
        # Add delivery company filtering
        if delivery_company_id and delivery_company_id != 'all':
            hourly_sales_query = hourly_sales_query.filter(Order.delivery_company_id == delivery_company_id)
        
        hourly_sales_query = hourly_sales_query.group_by(
            extract('hour', Order.created_at)
        ).order_by(
            extract('hour', Order.created_at)
        )
        
        hourly_data = hourly_sales_query.all()
        
        # Create 24-hour format with all hours (0-23)
        hours = list(range(24))
        order_counts = [0] * 24
        revenues = [0] * 24
        
        # Fill in actual data
        for item in hourly_data:
            hour_index = int(item.hour)
            if 0 <= hour_index <= 23:
                order_counts[hour_index] = item.order_count
                revenues[hour_index] = float(item.revenue or 0)
        
        # Format data for chart
        result = {
            'hours': [f"{hour:02d}:00" for hour in hours],
            'order_counts': order_counts,
            'revenues': revenues
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
