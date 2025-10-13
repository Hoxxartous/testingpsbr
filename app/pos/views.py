from flask import render_template, redirect, url_for, request, jsonify, flash, make_response, current_app
from flask_login import login_required, current_user
from flask_socketio import join_room, leave_room
from app.pos import pos
from app.models import (
    User, MenuItem, Category, Order, AuditLog, Table, Customer, UserRole, OrderItem, DeliveryCompany, ServiceType, OrderStatus, PaymentMethod, TimezoneManager, AdminPinCode, WaiterCashierAssignment, OrderEditHistory, CashierUiPreference, CashierUiSetting, OrderCounter, CashierPin, CashierSession, ManualCardPayment
)
from app import db, socketio
from app.auth.decorators import cashier_or_above_required, pos_access_required, filter_by_user_branch
from datetime import datetime, timedelta
import random
import string
from sqlalchemy import func
from sqlalchemy.exc import OperationalError, ProgrammingError
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as ReportTable, TableStyle, Image
from reportlab.lib.colors import HexColor, PCMYKColor
import io
import base64

# WebSocket event handlers
@socketio.on('join')
def on_join(data):
    """Handle user joining a room for real-time updates with enhanced isolation"""
    room = data['room']
    join_room(room)
    print(f"User {current_user.get_full_name()} joined room: {room}")
    
    # Auto-join appropriate rooms based on user role for enhanced isolation
    if current_user.role == UserRole.CASHIER:
        # Cashiers join their specific cashier room for targeted waiter requests
        cashier_room = f'cashier_{current_user.id}'
        join_room(cashier_room)
        print(f"Cashier {current_user.get_full_name()} auto-joined room: {cashier_room}")
        
        # Also join branch room for general notifications (order_paid, etc.)
        branch_room = f'branch_{current_user.branch_id}'
        if room != branch_room:  # Avoid duplicate join
            join_room(branch_room)
            print(f"Cashier {current_user.get_full_name()} auto-joined branch room: {branch_room}")
    
    elif current_user.role == UserRole.WAITER:
        # Waiters join their specific waiter room for their own order notifications
        waiter_room = f'waiter_{current_user.id}'
        join_room(waiter_room)
        print(f"Waiter {current_user.get_full_name()} auto-joined room: {waiter_room}")
        
        # Also join branch room for general notifications (but not for new_order events from other waiters)
        branch_room = f'branch_{current_user.branch_id}'
        if room != branch_room:  # Avoid duplicate join
            join_room(branch_room)
            print(f"Waiter {current_user.get_full_name()} auto-joined branch room: {branch_room}")
    
    elif current_user.role == UserRole.ADMIN:
        # Admins join branch room for their branch only
        branch_room = f'branch_{current_user.branch_id}'
        if room != branch_room:  # Avoid duplicate join
            join_room(branch_room)
            print(f"Admin {current_user.get_full_name()} auto-joined branch room: {branch_room}")
    
    elif current_user.role == UserRole.SUPER_ADMIN:
        # Super admins can join a special room to see all branch activity if needed
        super_admin_room = 'super_admin'
        if room != super_admin_room:  # Avoid duplicate join
            join_room(super_admin_room)
            print(f"Super Admin {current_user.get_full_name()} auto-joined super admin room: {super_admin_room}")

@socketio.on('disconnect')
def on_disconnect():
    """Handle user disconnection"""
    print(f"User {current_user.get_full_name()} disconnected")

@pos.before_request
@pos_access_required
def before_request():
    # Access control is handled by the decorator - allows cashiers and waiters
    pass

@pos.route('/')
def index():
    # Get URL parameters for table pre-selection and return URL
    selected_table_id = request.args.get('table_id', type=int)
    return_to = request.args.get('return_to')
    add_items = request.args.get('add_items') == 'true'  # Explicitly adding items to existing order
    new_order = request.args.get('new_order') == 'true'  # Starting a new order (take order)
    
    # Check if this is an "Add Items" request (existing order)
    existing_order = None
    existing_order_items = []
    
    # Only load existing items if this is explicitly an "Add Items" request
    if selected_table_id and add_items:
        # Get the most recent PENDING order for this table
        existing_order = Order.query.filter_by(
            table_id=selected_table_id,
            branch_id=current_user.branch_id,
            status=OrderStatus.PENDING
        ).order_by(Order.created_at.desc()).first()
        
        if existing_order:
            # For "Add Items" functionality, we should NOT load existing items in the cart
            # because this causes duplication. The waiter should start with a clean cart
            # and only add NEW items to the existing order.
            
            notes = existing_order.notes or ''
            has_added_items = '[ITEMS ADDED]' in notes
            
            if has_added_items:
                print(f"DEBUG: Order has previous additions, starting with clean cart for new items only")
            else:
                print(f"DEBUG: First addition to order, starting with clean cart")
            
            # Start with empty cart - waiter will add only NEW items
            existing_order_items = []
    
    # For "Take Order" (new_order=true), we start with empty cart even if there are old paid orders
    
    # Get active menu items and categories for current user's branch (automatically filtered)
    categories = filter_by_user_branch(
        Category.query.filter_by(is_active=True).order_by(Category.order_index), 
        Category
    ).all()
    items = filter_by_user_branch(
        MenuItem.query.filter_by(is_active=True), 
        MenuItem
    ).all()
    # Get tables with status information
    tables_query = filter_by_user_branch(
        Table.query.filter_by(is_active=True), 
        Table
    ).all()
    
    # Add status information to tables
    tables_with_status = []
    for table in tables_query:
        # Get the most recent order for this table
        recent_order = Order.query.filter_by(
            table_id=table.id,
            branch_id=current_user.branch_id
        ).order_by(Order.created_at.desc()).first()
        
        # Determine if table is busy (same logic as table management)
        is_busy = False
        if recent_order:
            from datetime import datetime, timedelta
            four_hours_ago = datetime.utcnow() - timedelta(hours=4)
            
            # Table is only busy if there's a PENDING order (not PAID)
            if (recent_order.created_at > four_hours_ago and 
                recent_order.status == OrderStatus.PENDING):
                is_busy = True
        
        tables_with_status.append({
            'id': table.id,
            'table_number': table.table_number,
            'is_busy': is_busy,
            'recent_order': recent_order
        })
    
    tables = tables_with_status
    
    # Get special requests category and items separately (branch-filtered)
    special_category = filter_by_user_branch(
        Category.query.filter_by(name='طلبات خاصة', is_active=True), 
        Category
    ).first()
    special_items = []
    if special_category:
        special_items = filter_by_user_branch(
            MenuItem.query.filter_by(category_id=special_category.id, is_active=True), 
            MenuItem
        ).all()
    
    # Preload UI preferences for initial paint (avoid flash)
    ui_prefs = {
        'card_width_pct': 50,
        'card_min_height_px': 160,
        'font_size_px': 14,
        'show_images': True,
        'price_badge_scale': 1.0,
        'name_badge_scale': 1.0,
        # Special items preferences
        'special_width_pct': 100,
        'special_height_px': 40,
        'special_font_px': 11,
        'special_spacing_px': 8,
        'special_sidebar_width': 100,
    }
    try:
        if current_user.is_authenticated and current_user.role and current_user.role.name in ['CASHIER', 'WAITER']:
            pref = CashierUiPreference.query.filter_by(
                cashier_id=current_user.id, branch_id=current_user.branch_id
            ).first()
            if pref:
                ui_prefs['card_width_pct'] = pref.card_width_pct
                ui_prefs['card_min_height_px'] = pref.card_min_height_px
            fs = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'font_size_px', '14')
            si = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'show_images', '1')
            ps = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'price_badge_scale', '1')
            ns = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'name_badge_scale', '1')
            ui_prefs['font_size_px'] = int(fs) if str(fs).isdigit() else 14
            ui_prefs['show_images'] = True if str(si) in ['1','true','True'] else False
            try:
                ui_prefs['price_badge_scale'] = float(ps)
            except Exception:
                ui_prefs['price_badge_scale'] = 1.0
            try:
                ui_prefs['name_badge_scale'] = float(ns)
            except Exception:
                ui_prefs['name_badge_scale'] = 1.0
            
            # Load special items preferences
            sw = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_width_pct', '100')
            sh = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_height_px', '40')
            sf = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_font_px', '11')
            ss = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_spacing_px', '8')
            ssw = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_sidebar_width', '100')
            ui_prefs['special_width_pct'] = int(sw) if str(sw).isdigit() else 100
            ui_prefs['special_height_px'] = int(sh) if str(sh).isdigit() else 40
            ui_prefs['special_font_px'] = int(sf) if str(sf).isdigit() else 11
            ui_prefs['special_spacing_px'] = int(ss) if str(ss).isdigit() else 8
            ui_prefs['special_sidebar_width'] = int(ssw) if str(ssw).isdigit() else 100
    except Exception:
        pass

    # Get cashiers in the same branch for waiter assignment
    branch_cashiers = []
    if current_user.role == UserRole.WAITER:
        branch_cashiers = User.query.filter_by(
            role=UserRole.CASHIER,
            branch_id=current_user.branch_id,
            is_active=True
        ).all()
    
    # Preload user-specific item colors to prevent flashing
    item_colors = {}
    if current_user.is_authenticated and current_user.role and current_user.role.name in ['CASHIER', 'WAITER']:
        for item in items:
            color_key = f'item_color_{item.id}'
            custom_color = CashierUiSetting.get_value(current_user.id, current_user.branch_id, color_key, '')
            if custom_color:
                item_colors[item.id] = custom_color
    
    return render_template('pos/index.html', 
                         categories=categories, 
                         items=items,
                         tables=tables,
                         branch_cashiers=branch_cashiers,
                         special_category=special_category,
                         special_items=special_items,
                         ui_prefs=ui_prefs,
                         item_colors=item_colors,
                         selected_table_id=selected_table_id,
                         return_to=return_to,
                         existing_order=existing_order,
                         existing_order_items=existing_order_items)

@pos.route('/save_item_customizations', methods=['POST'])
def save_item_customizations():
    """Save cashier-specific item customizations (colors, order)"""
    try:
        data = request.get_json()
        customizations = data.get('customizations', [])
        
        if not current_user.is_authenticated or current_user.role.name not in ['CASHIER', 'WAITER']:
            return jsonify({'success': False, 'message': 'Unauthorized'})
        
        # Process each customization
        for custom in customizations:
            item_id = custom.get('item_id')
            custom_color = custom.get('custom_color')
            display_order = custom.get('display_order')
            
            # Find the menu item
            item = filter_by_user_branch(
                MenuItem.query.filter_by(id=item_id),
                MenuItem
            ).first()
            
            if item:
                # Update item color per user if provided
                if custom_color:
                    color_key = f'item_color_{item_id}'
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, color_key, custom_color)
                elif custom_color == '':
                    # Remove custom color for this user
                    color_key = f'item_color_{item_id}'
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, color_key, '')
                
                # Update display order per user if provided
                if display_order is not None:
                    order_key = f'item_order_{item_id}'
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, order_key, str(display_order))
        
        # Log the customization change
        audit_log = AuditLog(
            user_id=current_user.id,
            action='CUSTOMIZE_ITEMS',
            description=f'Updated {len(customizations)} item customizations'
        )
        db.session.add(audit_log)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Customizations saved successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error saving customizations: {str(e)}'})

@pos.route('/get_item_customizations')
@login_required
def get_item_customizations():
    """Get saved item customizations (colors, order) for current cashier and branch"""
    try:
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'message': 'Unauthorized'})
        
        # Get all menu items for current branch
        items = filter_by_user_branch(
            MenuItem.query.filter_by(is_active=True),
            MenuItem
        ).all()
        
        customizations = []
        for item in items:
            # Get per-user customizations from CashierUiSetting
            color_key = f'item_color_{item.id}'
            order_key = f'item_order_{item.id}'
            
            custom_color = CashierUiSetting.get_value(current_user.id, current_user.branch_id, color_key, '')
            display_order = CashierUiSetting.get_value(current_user.id, current_user.branch_id, order_key, '0')
            
            customization = {
                'item_id': item.id,
                'custom_color': custom_color,
                'display_order': int(display_order) if display_order.isdigit() else 0
            }
            customizations.append(customization)
        
        return jsonify({
            'success': True, 
            'customizations': customizations
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error loading customizations: {str(e)}'})

@pos.route('/get_ui_prefs')
@login_required
def get_ui_prefs():
    """Return POS UI sizing preferences for current user and branch"""
    # Allow both cashiers and waiters to access UI preferences
    if current_user.role.name not in ['CASHIER', 'WAITER']:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        pref = CashierUiPreference.query.filter_by(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        ).first()
        if not pref:
            data = {'card_width_pct': 50, 'card_min_height_px': 160}
        else:
            data = pref.to_dict()
        # Add extra settings (font size, show images)
        font_size_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'font_size_px', '14')
        show_images = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'show_images', '1')
        price_scale = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'price_badge_scale', '1')
        name_scale = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'name_badge_scale', '1')
        data.update({
            'font_size_px': int(font_size_px) if str(font_size_px).isdigit() else 14,
            'show_images': True if str(show_images) in ['1', 'true', 'True'] else False,
            'price_badge_scale': float(price_scale) if str(price_scale) not in [None, ''] else 1.0,
            'name_badge_scale': float(name_scale) if str(name_scale) not in [None, ''] else 1.0,
        })
        return jsonify({'success': True, 'data': data})
    except (OperationalError, ProgrammingError):
        # Likely new tables not yet created; create all and retry once
        db.create_all()
        try:
            pref = CashierUiPreference.query.filter_by(
                cashier_id=current_user.id,
                branch_id=current_user.branch_id
            ).first()
            data = {'card_width_pct': 50, 'card_min_height_px': 160}
            if pref:
                data = pref.to_dict()
            font_size_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'font_size_px', '14')
            show_images = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'show_images', '1')
            price_scale = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'price_badge_scale', '1')
            name_scale = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'name_badge_scale', '1')
            data.update({
                'font_size_px': int(font_size_px) if str(font_size_px).isdigit() else 14,
                'show_images': True if str(show_images) in ['1', 'true', 'True'] else False,
                'price_badge_scale': float(price_scale) if str(price_scale) not in [None, ''] else 1.0,
                'name_badge_scale': float(name_scale) if str(name_scale) not in [None, ''] else 1.0,
            })
            return jsonify({'success': True, 'data': data})
        except Exception as e2:
            return jsonify({'success': False, 'error': str(e2)}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- Visual customization endpoints ---
@pos.route('/update_item_color', methods=['POST'])
@login_required
def update_item_color():
    """Update a single item's background color per user. Cashier or waiter.
    Payload: { item_id: int, color: '#RRGGBB' }
    """
    if current_user.role not in [UserRole.CASHIER, UserRole.WAITER, UserRole.MANAGER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
    data = request.get_json() or {}
    item_id = data.get('item_id')
    color = (data.get('color') or '').strip()
    try:
        if not item_id or not isinstance(item_id, int):
            return jsonify({'success': False, 'error': 'Invalid item_id'}), 400
        if not color or not color.startswith('#') or len(color) not in (4,7):
            return jsonify({'success': False, 'error': 'Invalid color'}), 400
        item = MenuItem.query.get(item_id)
        if not item or item.branch_id != current_user.branch_id:
            return jsonify({'success': False, 'error': 'Item not found'}), 404
        
        # Store color per user in CashierUiSetting instead of MenuItem
        color_key = f'item_color_{item_id}'
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, color_key, color)
        db.session.commit()
        return jsonify({'success': True, 'item_id': item_id, 'color': color})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@pos.route('/save_item_order', methods=['POST'])
@login_required
def save_item_order():
    """Persist per-category item order for this cashier+branch.
    Payload: { category_id: int, order: [item_ids...] }
    Stored in CashierUiSetting key: order_cat_<category_id>
    """
    if current_user.role.name not in ['CASHIER', 'WAITER']:
        return jsonify({'success': False, 'error': 'Only cashiers and waiters can save ordering'}), 403
    payload = request.get_json() or {}
    cat_id = payload.get('category_id')
    order = payload.get('order') or []
    try:
        if not isinstance(cat_id, int) or not isinstance(order, list) or not all(isinstance(x, int) for x in order):
            return jsonify({'success': False, 'error': 'Invalid payload'}), 400
        # Basic validation: ensure items belong to branch
        count = MenuItem.query.filter(MenuItem.id.in_(order), MenuItem.branch_id == current_user.branch_id).count()
        if count != len(order):
            return jsonify({'success': False, 'error': 'Some items invalid for branch'}), 400
        key = f'order_cat_{cat_id}'
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, key, ','.join(str(i) for i in order))
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@pos.route('/save_ui_prefs', methods=['POST'])
@login_required
def save_ui_prefs():
    """Save POS UI sizing preferences for current user and branch"""
    if current_user.role.name not in ['CASHIER', 'WAITER']:
        return jsonify({'success': False, 'error': 'Only cashiers and waiters can save preferences'}), 403
    try:
        payload = request.get_json() or {}
        width_pct = int(payload.get('card_width_pct', 50))
        height_px = int(payload.get('card_min_height_px', 160))
        # Clamp values to broader, still reasonable ranges
        # Width: 10%..100%, Height: 80..500px
        width_pct = max(10, min(100, width_pct))
        height_px = max(80, min(500, height_px))

        # Optional extras
        font_size_px = payload.get('font_size_px', None)
        show_images = payload.get('show_images', None)
        price_badge_scale = payload.get('price_badge_scale', None)
        name_badge_scale = payload.get('name_badge_scale', None)

        pref = CashierUiPreference.query.filter_by(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        ).first()
        if not pref:
            pref = CashierUiPreference(
                cashier_id=current_user.id,
                branch_id=current_user.branch_id,
                card_width_pct=width_pct,
                card_min_height_px=height_px
            )
            db.session.add(pref)
        else:
            pref.card_width_pct = width_pct
            pref.card_min_height_px = height_px
        # Save extra settings via KV store
        if font_size_px is not None:
            try:
                font_val = int(font_size_px)
                font_val = max(10, min(32, font_val))
                CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'font_size_px', str(font_val))
            except Exception:
                pass
        if show_images is not None:
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'show_images', '1' if bool(show_images) in [True] or str(show_images) in ['1','true','True'] else '0')
        if price_badge_scale is not None:
            try:
                p = float(price_badge_scale)
                p = max(0.5, min(2.0, p))
                CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'price_badge_scale', str(p))
            except Exception:
                pass
        if name_badge_scale is not None:
            try:
                n = float(name_badge_scale)
                n = max(0.5, min(2.0, n))
                CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'name_badge_scale', str(n))
            except Exception:
                pass

        db.session.commit()
        # Compose response
        result = pref.to_dict()
        result['font_size_px'] = int(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'font_size_px', '14'))
        result['show_images'] = True if CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'show_images', '1') in ['1','true','True'] else False
        result['price_badge_scale'] = float(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'price_badge_scale', '1'))
        result['name_badge_scale'] = float(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'name_badge_scale', '1'))
        return jsonify({'success': True, 'data': result})
    except (OperationalError, ProgrammingError):
        # Create tables and retry once
        db.create_all()
        try:
            payload = request.get_json() or {}
            width_pct = int(payload.get('card_width_pct', 50))
            height_px = int(payload.get('card_min_height_px', 160))
            width_pct = max(10, min(100, width_pct))
            height_px = max(80, min(500, height_px))
            font_size_px = payload.get('font_size_px', None)
            show_images = payload.get('show_images', None)
            price_badge_scale = payload.get('price_badge_scale', None)
            name_badge_scale = payload.get('name_badge_scale', None)

            pref = CashierUiPreference.query.filter_by(
                cashier_id=current_user.id,
                branch_id=current_user.branch_id
            ).first()
            if not pref:
                pref = CashierUiPreference(
                    cashier_id=current_user.id,
                    branch_id=current_user.branch_id,
                    card_width_pct=width_pct,
                    card_min_height_px=height_px
                )
                db.session.add(pref)
            else:
                pref.card_width_pct = width_pct
                pref.card_min_height_px = height_px

            if font_size_px is not None:
                try:
                    font_val = int(font_size_px)
                    font_val = max(10, min(32, font_val))
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'font_size_px', str(font_val))
                except Exception:
                    pass
            if show_images is not None:
                CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'show_images', '1' if bool(show_images) in [True] or str(show_images) in ['1','true','True'] else '0')
            if price_badge_scale is not None:
                try:
                    p = float(price_badge_scale)
                    p = max(0.5, min(2.0, p))
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'price_badge_scale', str(p))
                except Exception:
                    pass
            if name_badge_scale is not None:
                try:
                    n = float(name_badge_scale)
                    n = max(0.5, min(2.0, n))
                    CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'name_badge_scale', str(n))
                except Exception:
                    pass

            db.session.commit()
            result = pref.to_dict()
            result['font_size_px'] = int(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'font_size_px', '14'))
            result['show_images'] = True if CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'show_images', '1') in ['1','true','True'] else False
            result['price_badge_scale'] = float(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'price_badge_scale', '1'))
            result['name_badge_scale'] = float(CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'name_badge_scale', '1'))
            return jsonify({'success': True, 'data': result})
        except Exception as e2:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e2)}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@pos.route('/dashboard')
def dashboard():
    # Prevent waiters from accessing dashboard
    if current_user.role == UserRole.WAITER:
        flash('Access denied. Dashboard is not available for waiters.', 'error')
        return redirect(url_for('pos.table_management'))
    
    # Dashboard shows different data based on user role
    today = datetime.utcnow().date()
    
    # Build base query based on user role
    if current_user.role == UserRole.SUPER_USER:
        # Super users see all orders
        base_query = Order.query
    elif current_user.role == UserRole.BRANCH_ADMIN:
        # Branch admins see all orders in their branch
        base_query = Order.query.filter_by(branch_id=current_user.branch_id)
    elif current_user.role == UserRole.CASHIER:
        # Cashiers see orders they created + orders assigned to them by waiters
        base_query = Order.query.filter(
            db.or_(
                Order.cashier_id == current_user.id,  # Orders they created
                Order.assigned_cashier_id == current_user.id  # Orders assigned to them
            )
        )
    else:
        # Fallback
        base_query = Order.query.filter_by(cashier_id=current_user.id)
    
    # Total orders: ALL orders for this user/role
    total_orders = base_query.count()
    # Sales: Only PAID orders count toward revenue
    today_sales = db.session.query(func.sum(Order.total_amount)).filter(
        func.date(Order.created_at) == today,
        Order.status == OrderStatus.PAID
    )
    if current_user.role == UserRole.SUPER_USER:
        pass  # No additional filter
    elif current_user.role == UserRole.BRANCH_ADMIN:
        today_sales = today_sales.filter(Order.branch_id == current_user.branch_id)
    elif current_user.role == UserRole.CASHIER:
        today_sales = today_sales.filter(
            db.or_(
                Order.cashier_id == current_user.id,
                Order.assigned_cashier_id == current_user.id
            )
        )
    today_sales = today_sales.scalar() or 0
    
    # Recent orders for current user
    recent_orders = base_query.order_by(Order.created_at.desc()).limit(10).all()
    
    # Orders by day for the last 7 days - role-based
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    daily_sales_query = db.session.query(
        func.date(Order.created_at).label('date'),
        func.sum(Order.total_amount).label('total')
    ).filter(
        Order.status == OrderStatus.PAID,
        Order.created_at >= start_date
    )
    
    # Apply role-based filtering to daily sales
    if current_user.role == UserRole.SUPER_USER:
        pass  # No additional filter
    elif current_user.role == UserRole.BRANCH_ADMIN:
        daily_sales_query = daily_sales_query.filter(Order.branch_id == current_user.branch_id)
    elif current_user.role == UserRole.CASHIER:
        daily_sales_query = daily_sales_query.filter(
            db.or_(
                Order.cashier_id == current_user.id,
                Order.assigned_cashier_id == current_user.id
            )
        )
    
    daily_sales = daily_sales_query.group_by(
        func.date(Order.created_at)
    ).order_by(
        func.date(Order.created_at)
    ).all()
    
    # Convert date objects to strings for JSON serialization
    daily_sales_serializable = []
    for sale in daily_sales:
        # Check the type of sale.date to debug the issue
        print(f"Type of sale.date: {type(sale.date)}, Value: {sale.date}")
        # If it's already a string, use it directly, otherwise format it
        if isinstance(sale.date, str):
            formatted_date = sale.date
        else:
            formatted_date = sale.date.strftime('%a, %b %d') if sale.date else None
            
        daily_sales_serializable.append({
            'date': formatted_date,
            'total': float(sale.total) if sale.total else 0
        })
    
    # Today's orders count - ALL orders (including pending waiter orders)
    today_orders_query = base_query.filter(func.date(Order.created_at) == today)
    today_orders = today_orders_query.count()
    
    # Total revenue (all time) - only PAID orders
    total_revenue_query = db.session.query(func.sum(Order.total_amount)).filter(Order.status == OrderStatus.PAID)
    if current_user.role == UserRole.SUPER_USER:
        pass  # No additional filter
    elif current_user.role == UserRole.BRANCH_ADMIN:
        total_revenue_query = total_revenue_query.filter(Order.branch_id == current_user.branch_id)
    elif current_user.role == UserRole.CASHIER:
        total_revenue_query = total_revenue_query.filter(
            db.or_(
                Order.cashier_id == current_user.id,
                Order.assigned_cashier_id == current_user.id
            )
        )
    total_revenue = total_revenue_query.scalar() or 0
    
    # Add waiter-specific statistics for cashiers
    waiter_stats = {}
    if current_user.role == UserRole.CASHIER:
        # Get waiter orders statistics for today (only orders assigned to this cashier)
        waiter_orders_today = Order.query.filter(
            Order.assigned_cashier_id == current_user.id,
            Order.notes.like('%[WAITER ORDER]%'),
            func.date(Order.created_at) == today
        ).count()
        
        waiter_sales_today = db.session.query(func.sum(Order.total_amount)).filter(
            Order.assigned_cashier_id == current_user.id,
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PAID,
            func.date(Order.created_at) == today
        ).scalar() or 0
        
        pending_waiter_orders = Order.query.filter(
            Order.assigned_cashier_id == current_user.id,
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PENDING
        ).count()
        
        waiter_stats = {
            'orders_today': waiter_orders_today,
            'sales_today': float(waiter_sales_today),
            'pending_orders': pending_waiter_orders
        }
    
    # Get manual card payment for today (for cashiers only)
    manual_card_payment_today = None
    if current_user.role == UserRole.CASHIER:
        manual_card_payment_today = ManualCardPayment.get_cashier_entry_for_date(
            current_user.id, today
        )
    
    # Include manual card payments in revenue calculations
    manual_card_total_today = 0
    manual_card_total_all_time = 0
    
    if current_user.role == UserRole.CASHIER:
        # For cashiers, only their own manual card payments
        manual_card_total_today = ManualCardPayment.get_total_for_date_and_branch(today, current_user.branch_id)
        manual_card_total_all_time = ManualCardPayment.get_total_for_date_range_and_branch(
            datetime(2020, 1, 1).date(), today, current_user.branch_id
        )
    elif current_user.role in [UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        # For admins, all manual card payments in their scope
        if current_user.role == UserRole.BRANCH_ADMIN:
            manual_card_total_today = ManualCardPayment.get_total_for_date_and_branch(today, current_user.branch_id)
            manual_card_total_all_time = ManualCardPayment.get_total_for_date_range_and_branch(
                datetime(2020, 1, 1).date(), today, current_user.branch_id
            )
        else:  # SUPER_USER
            manual_card_total_today = db.session.query(func.sum(ManualCardPayment.amount)).filter(
                ManualCardPayment.date == today
            ).scalar() or 0
            manual_card_total_all_time = db.session.query(func.sum(ManualCardPayment.amount)).scalar() or 0
    
    # Update totals to include manual card payments
    today_sales_with_cards = today_sales + manual_card_total_today
    total_revenue_with_cards = total_revenue + manual_card_total_all_time
    
    return render_template('pos/dashboard.html',
                          total_orders=total_orders,
                          today_sales=today_sales_with_cards,
                          today_orders=today_orders,
                          total_revenue=total_revenue_with_cards,
                          recent_orders=recent_orders,
                          daily_sales=daily_sales_serializable,
                          waiter_stats=waiter_stats,
                          manual_card_payment_today=manual_card_payment_today,
                          manual_card_total_today=manual_card_total_today)

@pos.route('/daily_report')
@login_required
def daily_report():
    # Only allow cashiers to generate their daily report
    if current_user.role.name != 'CASHIER':
        flash('Access denied. Cashier privileges required.', 'error')
        return redirect(url_for('pos.index'))
    
    # CRITICAL: Check for unpaid waiter orders - MUST be processed first
    unpaid_waiter_orders = Order.query.filter(
        Order.assigned_cashier_id == current_user.id,
        Order.notes.like('%[WAITER ORDER]%'),
        Order.status == OrderStatus.PENDING
    ).count()
    
    if unpaid_waiter_orders > 0:
        flash(f'Cannot generate report! You have {unpaid_waiter_orders} unpaid waiter orders. Process or transfer them first.', 'error')
        return redirect(url_for('pos.waiter_requests'))
    
    # Generate daily statistics only
    today = datetime.utcnow().date()
    
    # Today's statistics - Include both created and assigned orders
    today_orders = Order.query.filter(
        db.or_(
            Order.cashier_id == current_user.id,
            Order.assigned_cashier_id == current_user.id
        ),
        func.date(Order.created_at) == today
    ).count()
    
    today_sales = db.session.query(func.sum(Order.total_amount)).filter(
        db.or_(
            Order.cashier_id == current_user.id,
            Order.assigned_cashier_id == current_user.id
        ),
        Order.status == OrderStatus.PAID,  # Only count PAID orders for revenue
        func.date(Order.created_at) == today
    ).scalar() or 0
    
    # Get today's most popular items - Include both created and assigned orders
    popular_items = db.session.query(
        MenuItem.name,
        func.sum(OrderItem.quantity).label('total_quantity'),
        func.sum(OrderItem.total_price).label('total_revenue')
    ).join(OrderItem, MenuItem.id == OrderItem.menu_item_id)\
     .join(Order, OrderItem.order_id == Order.id)\
     .filter(
         db.or_(
             Order.cashier_id == current_user.id,
             Order.assigned_cashier_id == current_user.id
         ),
         func.date(Order.created_at) == today
     )\
     .group_by(MenuItem.id, MenuItem.name)\
     .order_by(func.sum(OrderItem.quantity).desc())\
     .limit(5).all()
    
    # Get waiter order statistics for today
    waiter_orders_today = Order.query.filter(
        Order.assigned_cashier_id == current_user.id,
        Order.notes.like('%[WAITER ORDER]%'),
        func.date(Order.created_at) == today
    ).count()
    
    waiter_orders_paid = Order.query.filter(
        Order.assigned_cashier_id == current_user.id,
        Order.notes.like('%[WAITER ORDER]%'),
        Order.status == OrderStatus.PAID,
        func.date(Order.created_at) == today
    ).count()
    
    waiter_orders_pending = Order.query.filter(
        Order.assigned_cashier_id == current_user.id,
        Order.notes.like('%[WAITER ORDER]%'),
        Order.status == OrderStatus.PENDING,
        func.date(Order.created_at) == today
    ).count()
    
    waiter_sales_today = db.session.query(func.sum(Order.total_amount)).filter(
        Order.assigned_cashier_id == current_user.id,
        Order.notes.like('%[WAITER ORDER]%'),
        Order.status == OrderStatus.PAID,
        func.date(Order.created_at) == today
    ).scalar() or 0
    
    # Generate PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center alignment
        textColor=HexColor('#2c3e50')
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        textColor=HexColor('#34495e')
    )
    
    # Header
    elements.append(Paragraph("🍽️ Restaurant POS", title_style))
    elements.append(Paragraph("Daily Cashier Report", title_style))
    elements.append(Spacer(1, 20))
    
    # Cashier info
    cashier_info = f"""
    <b>Cashier:</b> {current_user.get_full_name()}<br/>
    <b>Date:</b> {today.strftime('%A, %B %d, %Y')}<br/>
    <b>Report Generated:</b> {datetime.now().strftime('%I:%M %p')}
    """
    elements.append(Paragraph(cashier_info, styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Today's Performance
    elements.append(Paragraph("[INFO] Today's Performance", heading_style))
    today_data = [
        ['Metric', 'Value'],
        ['Orders Processed', str(today_orders)],
        ['Revenue Generated', f'{float(today_sales):.2f} QAR'],
        ['Shift Start Time', datetime.now().strftime('%I:%M %p')],
        ['Report Generation Time', datetime.now().strftime('%I:%M %p')]
    ]
    
    today_table = ReportTable(today_data, colWidths=[3*inch, 2*inch])
    today_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#ecf0f1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(today_table)
    elements.append(Spacer(1, 20))
    
    # Today's Popular Items
    if popular_items:
        elements.append(Paragraph("🏆 Today's Top Selling Items", heading_style))
        items_data = [['Item Name', 'Quantity Sold', 'Revenue (QAR)']]
        
        for item in popular_items:
            items_data.append([
                item.name,
                str(item.total_quantity or 0),
                f'{float(item.total_revenue or 0):.2f}'
            ])
        
        items_table = ReportTable(items_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#27ae60')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), HexColor('#d5f4e6')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 20))
    
    # Waiter Orders Section
    if waiter_orders_today > 0:
        elements.append(Paragraph("👥 Waiter Orders Processed", heading_style))
        waiter_data = [
            ['Metric', 'Value'],
            ['Total Waiter Orders', str(waiter_orders_today)],
            ['Orders Paid', str(waiter_orders_paid)],
            ['Orders Pending', str(waiter_orders_pending)],
            ['Waiter Orders Revenue', f'{float(waiter_sales_today):.2f} QAR']
        ]
        
        waiter_table = ReportTable(waiter_data, colWidths=[3*inch, 2*inch])
        waiter_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#e74c3c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), HexColor('#fadbd8')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(waiter_table)
        elements.append(Spacer(1, 20))
        
        # Warning if there are pending orders
        if waiter_orders_pending > 0:
            warning_text = f"""
            <b>[WARNING] WARNING:</b> You have {waiter_orders_pending} unpaid waiter orders!<br/>
            These orders must be processed or transferred before logout.
            """
            warning_style = ParagraphStyle(
                'Warning',
                parent=styles['Normal'],
                fontSize=12,
                textColor=HexColor('#e74c3c'),
                spaceAfter=12
            )
            elements.append(Paragraph(warning_text, warning_style))
            elements.append(Spacer(1, 10))
    
    # Footer
    footer_text = """
    <b>📋 Manager Notes:</b><br/>
    • This report summarizes the cashier's daily performance<br/>
    • All financial figures are in QAR (Qatari Riyal)<br/>
    • Report must be submitted to management before shift end<br/>
    <br/>
    <i>Generated by Restaurant POS System - Professional Edition</i>
    """
    elements.append(Paragraph(footer_text, styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    # Get PDF data
    pdf_data = buffer.getvalue()
    buffer.close()
    
    # FIXED: Automatically mark report as printed when PDF is generated
    # This ensures logout prevention works regardless of how the PDF is accessed
    try:
        session = CashierSession.get_or_create_today_session(current_user.id)
        # Ensure session has correct branch
        if session and not session.branch_id:
            session.branch_id = current_user.branch_id
        session.mark_report_printed()
        print(f"DAILY REPORT GENERATED AND MARKED: Cashier {current_user.get_full_name()} - Session {session.session_id}")
        
        # Create audit log entry for daily report generation
        audit_log = AuditLog(
            user_id=current_user.id,
            action='DAILY_REPORT_GENERATED',
            description=f'Cashier {current_user.get_full_name()} printed daily report for {today.strftime("%Y-%m-%d")}',
            ip_address=request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR'))
        )
        db.session.add(audit_log)
        db.session.commit()
        
    except Exception as session_error:
        print(f"Warning: Could not mark report as printed or log audit: {session_error}")
    
    # Create response
    response = make_response(pdf_data)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=daily_report_{current_user.username}_{today.strftime("%Y%m%d")}.pdf'
    
    return response

@pos.route('/get_today_orders_count')
@login_required
def get_today_orders_count():
    """Get today's order count for the current cashier"""
    # Only allow cashiers to access this endpoint
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    try:
        today = datetime.utcnow().date()
        
        # Count today's orders for this cashier
        today_orders_count = Order.query.filter(
            Order.cashier_id == current_user.id,
            func.date(Order.created_at) == today
        ).count()
        
        return jsonify({
            'success': True,
            'count': today_orders_count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@pos.route('/ensure_cashier_session', methods=['POST'])
@login_required
def ensure_cashier_session():
    """Ensure cashier has an active session for today"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    try:
        today = datetime.utcnow().date()
        
        # Check if there's already an active session for today
        existing_session = CashierSession.query.filter(
            CashierSession.cashier_id == current_user.id,
            CashierSession.login_date == today,
            CashierSession.is_active == True
        ).first()
        
        if existing_session:
            # Update the existing session's last activity and current order count
            today_orders_count = Order.query.filter(
                Order.cashier_id == current_user.id,
                func.date(Order.created_at) == today
            ).count()
            existing_session.update_order_count(today_orders_count)
            
            return jsonify({
                'success': True,
                'session_id': existing_session.session_id,
                'initial_count': existing_session.initial_order_count,
                'current_count': existing_session.current_order_count,
                'existing_session': True
            })
        
        # Get current order count for today
        today_orders_count = Order.query.filter(
            Order.cashier_id == current_user.id,
            func.date(Order.created_at) == today
        ).count()
        
        # Create new session - use Flask session ID as unique identifier
        from flask import session
        session_id = f"cashier_{current_user.id}_{today}_{session.get('_id', 'unknown')}"
        
        new_session = CashierSession(
            session_id=session_id,
            login_date=today,
            initial_order_count=today_orders_count,
            current_order_count=today_orders_count,
            cashier_id=current_user.id,
            branch_id=current_user.branch_id
        )
        
        db.session.add(new_session)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'initial_count': today_orders_count,
            'current_count': today_orders_count,
            'existing_session': False
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        })

@pos.route('/update_session_order_count', methods=['POST'])
@login_required
def update_session_order_count():
    """Update the current order count for the active session"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    try:
        today = datetime.utcnow().date()
        
        # Get current order count for today
        today_orders_count = Order.query.filter(
            Order.cashier_id == current_user.id,
            func.date(Order.created_at) == today
        ).count()
        
        # Find active session for today
        active_session = CashierSession.query.filter(
            CashierSession.cashier_id == current_user.id,
            CashierSession.login_date == today,
            CashierSession.is_active == True
        ).first()
        
        if active_session:
            active_session.update_order_count(today_orders_count)
            
            return jsonify({
                'success': True,
                'current_count': today_orders_count,
                'initial_count': active_session.initial_order_count,
                'has_completed_orders': active_session.has_completed_orders()
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No active session found'
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@pos.route('/check_logout_permission')
@login_required
def check_logout_permission():
    """
    COMPREHENSIVE LOGOUT CHECK - INCLUDES WAITER ORDERS
    Rules: 
    1. If cashier has orders (created OR assigned) AFTER their last report print = BLOCK
    2. If cashier has unpaid waiter orders assigned to them = BLOCK
    """
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': True, 'can_logout': True})
    
    try:
        today = datetime.utcnow().date()
        cashier_id = current_user.id
        
        # STEP 1: Get the most recent report print time for this cashier today
        latest_report_session = CashierSession.query.filter(
            CashierSession.cashier_id == cashier_id,
            CashierSession.login_date == today,
            CashierSession.daily_report_printed == True,
            CashierSession.report_printed_at.isnot(None)
        ).order_by(CashierSession.report_printed_at.desc()).first()
        
        if latest_report_session:
            last_report_time = latest_report_session.report_printed_at
            # Count orders (created OR assigned) AFTER the last report was printed
            orders_after_report = Order.query.filter(
                db.or_(
                    Order.cashier_id == cashier_id,
                    Order.assigned_cashier_id == cashier_id
                ),
                func.date(Order.created_at) == today,
                Order.created_at > last_report_time
            ).count()
        else:
            # No report printed today - count ALL orders today (created OR assigned)
            last_report_time = None
            orders_after_report = Order.query.filter(
                db.or_(
                    Order.cashier_id == cashier_id,
                    Order.assigned_cashier_id == cashier_id
                ),
                func.date(Order.created_at) == today
            ).count()
        
        # STEP 2: Check for unpaid waiter orders assigned to this cashier
        unpaid_waiter_orders = Order.query.filter(
            Order.assigned_cashier_id == cashier_id,
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PENDING
        ).count()
        
        # STEP 3: Total orders today (for display) - created OR assigned
        total_orders_today = Order.query.filter(
            db.or_(
                Order.cashier_id == cashier_id,
                Order.assigned_cashier_id == cashier_id
            ),
            func.date(Order.created_at) == today
        ).count()
        
        # STEP 4: Apply the rules
        needs_report = orders_after_report > 0
        has_unpaid_waiter_orders = unpaid_waiter_orders > 0
        
        # Debug output with session information
        import sys
        from flask import session as flask_session
        
        # Get current session info
        browser_session_id = flask_session.get('_id', 'No session ID')
        user_session_info = f"User: {current_user.username} ({current_user.get_full_name()})"
        
        # Get cashier session info
        current_cashier_session = CashierSession.query.filter(
            CashierSession.cashier_id == cashier_id,
            CashierSession.login_date == today,
            CashierSession.is_active == True
        ).first()
        
        cashier_session_id = current_cashier_session.session_id if current_cashier_session else "No active session"
        
        sys.stdout.flush()
        print(f"\n=== COMPREHENSIVE LOGOUT CHECK DEBUG ===")
        print(f"Browser Session ID: {browser_session_id}")
        print(f"Cashier Session ID: {cashier_session_id}")
        print(f"{user_session_info}")
        print(f"Cashier ID: {cashier_id}")
        print(f"Total orders today: {total_orders_today}")
        print(f"Last report time: {last_report_time}")
        print(f"Orders after last report: {orders_after_report}")
        print(f"Unpaid waiter orders: {unpaid_waiter_orders}")
        print(f"Needs report: {needs_report}")
        print(f"Has unpaid waiter orders: {has_unpaid_waiter_orders}")
        print(f"==========================================\n")
        sys.stdout.flush()
        
        # STEP 5: Determine blocking conditions and response
        # IMPORTANT: Report is ALWAYS required if there are orders after last report
        # Unpaid waiter orders are an ADDITIONAL requirement that must be resolved first
        
        if needs_report and has_unpaid_waiter_orders:
            return jsonify({
                'success': True,
                'can_logout': False,
                'reason': f'You have {orders_after_report} orders since your last report AND {unpaid_waiter_orders} unpaid waiter orders. You must first process/transfer all unpaid waiter orders, then generate your daily report!',
                'orders_today': total_orders_today,
                'orders_after_report': orders_after_report,
                'unpaid_waiter_orders': unpaid_waiter_orders,
                'last_report_time': TimezoneManager.format_local_time(last_report_time, '%Y-%m-%d %H:%M:%S') if last_report_time else None,
                'action_required': 'both'  # Both report and waiter orders
            })
        elif needs_report and not has_unpaid_waiter_orders:
            return jsonify({
                'success': True,
                'can_logout': False,
                'reason': f'You have {orders_after_report} orders since your last report. Generate your daily report to logout!',
                'orders_today': total_orders_today,
                'orders_after_report': orders_after_report,
                'unpaid_waiter_orders': unpaid_waiter_orders,
                'last_report_time': TimezoneManager.format_local_time(last_report_time, '%Y-%m-%d %H:%M:%S') if last_report_time else None,
                'action_required': 'report'  # Only report needed
            })
        elif not needs_report and has_unpaid_waiter_orders:
            return jsonify({
                'success': True,
                'can_logout': False,
                'reason': f'You have {unpaid_waiter_orders} unpaid waiter orders. Process all waiter orders or transfer them to another cashier, then generate your daily report!',
                'orders_today': total_orders_today,
                'orders_after_report': orders_after_report,
                'unpaid_waiter_orders': unpaid_waiter_orders,
                'last_report_time': TimezoneManager.format_local_time(last_report_time, '%Y-%m-%d %H:%M:%S') if last_report_time else None,
                'action_required': 'waiter_orders_then_report'  # Process waiter orders, then report will be required
            })
        else:
            return jsonify({
                'success': True,
                'can_logout': True,
                'reason': 'No new orders since last report and no unpaid waiter orders' if last_report_time else 'No orders today',
                'orders_today': total_orders_today,
                'orders_after_report': orders_after_report,
                'unpaid_waiter_orders': unpaid_waiter_orders,
                'action_required': 'none'  # Can logout safely
            })
            
    except Exception as e:
        import sys
        print(f"\nERROR in logout check: {e}\n")
        sys.stdout.flush()
        return jsonify({
            'success': True,
            'can_logout': True,
            'reason': 'System error - logout allowed'
        })

@pos.route('/debug_logout_status')
@login_required
def debug_logout_status():
    """Debug endpoint to check current logout status for cashier"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'error': 'Only for cashiers'})
    
    try:
        today = datetime.utcnow().date()
        cashier_id = current_user.id
        
        # Get all sessions for today
        sessions = CashierSession.query.filter(
            CashierSession.cashier_id == cashier_id,
            CashierSession.login_date == today
        ).all()
        
        # Get orders today
        orders_today = Order.query.filter(
            Order.cashier_id == cashier_id,
            func.date(Order.created_at) == today
        ).all()
        
        # Check logout permission
        logout_check = check_logout_permission()
        
        return jsonify({
            'cashier': current_user.get_full_name(),
            'cashier_id': cashier_id,
            'date': today.isoformat(),
            'sessions': [{
                'id': s.id,
                'session_id': s.session_id,
                'initial_count': s.initial_order_count,
                'current_count': s.current_order_count,
                'daily_report_printed': s.daily_report_printed,
                'report_printed_at': TimezoneManager.format_local_time(s.report_printed_at, '%Y-%m-%d %H:%M:%S') if s.report_printed_at else None,
                'is_active': s.is_active
            } for s in sessions],
            'orders_today': len(orders_today),
            'order_numbers': [o.order_number for o in orders_today],
            'logout_permission': logout_check.get_json()
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@pos.route('/debug_session')
@login_required
def debug_session():
    """Debug endpoint to check session status"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'error': 'Access denied'})
    
    try:
        today = datetime.utcnow().date()
        
        # Get all sessions for today
        sessions = CashierSession.query.filter(
            CashierSession.cashier_id == current_user.id,
            CashierSession.login_date == today
        ).all()
        
        # Get current order count
        today_orders_count = Order.query.filter(
            Order.cashier_id == current_user.id,
            func.date(Order.created_at) == today
        ).count()
        
        session_data = []
        for s in sessions:
            session_data.append({
                'id': s.id,
                'session_id': s.session_id,
                'initial_count': s.initial_order_count,
                'current_count': s.current_order_count,
                'daily_report_printed': s.daily_report_printed,
                'is_active': s.is_active,
                'has_completed_orders': s.has_completed_orders(),
                'needs_daily_report': s.needs_daily_report()
            })
        
        return jsonify({
            'cashier_id': current_user.id,
            'today_orders_count': today_orders_count,
            'sessions': session_data
        })
        
    except Exception as e:
        return jsonify({'error': str(e)})

@pos.route('/transfer_orders', methods=['POST'])
@login_required
def transfer_orders():
    """Transfer unpaid waiter orders from current cashier to another cashier in same branch"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Only cashiers can transfer orders'})
    
    try:
        data = request.get_json()
        order_ids = data.get('order_ids', [])
        target_cashier_id = data.get('target_cashier_id')
        
        if not order_ids or not target_cashier_id:
            return jsonify({'success': False, 'error': 'Missing order IDs or target cashier'})
        
        # Validate target cashier
        target_cashier = User.query.get(target_cashier_id)
        if not target_cashier or target_cashier.branch_id != current_user.branch_id or target_cashier.role.name != 'CASHIER':
            return jsonify({'success': False, 'error': 'Invalid target cashier'})
        
        # Get orders to transfer
        orders_to_transfer = Order.query.filter(
            Order.id.in_(order_ids),
            Order.assigned_cashier_id == current_user.id,
            Order.status == OrderStatus.PENDING,
            Order.notes.like('%[WAITER ORDER]%')
        ).all()
        
        if len(orders_to_transfer) != len(order_ids):
            return jsonify({'success': False, 'error': 'Some orders cannot be transferred'})
        
        # Transfer orders
        transferred_count = 0
        for order in orders_to_transfer:
            # Update assigned cashier
            old_cashier_name = current_user.get_full_name()
            new_cashier_name = target_cashier.get_full_name()
            
            order.assigned_cashier_id = target_cashier_id
            
            # Update notes to reflect transfer
            transfer_note = f"\n[TRANSFERRED] From: {old_cashier_name} to: {new_cashier_name} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            order.notes = order.notes + transfer_note
            
            transferred_count += 1
            
            # Create audit log
            audit_log = AuditLog(
                user_id=current_user.id,
                action='ORDER_TRANSFERRED',
                description=f'Order {order.order_number} transferred from {old_cashier_name} to {new_cashier_name}',
                ip_address=request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR'))
            )
            db.session.add(audit_log)
        # Commit all changes
        db.session.commit()
        
        # ISOLATION: Emit WebSocket events for order transfers
        if transferred_count > 0:
            # Notify the target cashier about new orders assigned to them
            socketio.emit('orders_transferred_to_you', {
                'transferred_count': transferred_count,
                'from_cashier': current_user.get_full_name(),
                'order_ids': order_ids,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'cashier_{target_cashier_id}')
            
            # Notify the current cashier about successful transfer
            socketio.emit('orders_transferred_from_you', {
                'transferred_count': transferred_count,
                'to_cashier': target_cashier.get_full_name(),
                'order_ids': order_ids,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'cashier_{current_user.id}')
            
            print(f"ISOLATION: Transfer notifications sent - {transferred_count} orders from cashier_{current_user.id} to cashier_{target_cashier_id}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully transferred {transferred_count} orders to {target_cashier.get_full_name()}',
            'transferred_count': transferred_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@pos.route('/get_branch_cashiers')
@login_required
def get_branch_cashiers():
    """Get list of cashiers in current user's branch (excluding current user)"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Only cashiers can access this'})
    
    try:
        cashiers = User.query.filter(
            User.branch_id == current_user.branch_id,
            User.role == UserRole.CASHIER,
            User.id != current_user.id,
            User.is_active == True
        ).all()
        
        cashier_list = [{
            'id': cashier.id,
            'name': cashier.get_full_name(),
            'username': cashier.username
        } for cashier in cashiers]
        
        return jsonify({
            'success': True,
            'cashiers': cashier_list
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@pos.route('/get_unpaid_waiter_orders')
@login_required
def get_unpaid_waiter_orders():
    """Get unpaid waiter orders assigned to current cashier"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Only cashiers can access this'})
    
    try:
        orders = Order.query.filter(
            Order.assigned_cashier_id == current_user.id,
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PENDING
        ).order_by(Order.created_at.desc()).all()
        
        order_list = []
        for order in orders:
            # Extract waiter name from notes
            waiter_name = "Unknown Waiter"
            if "Created by:" in order.notes:
                try:
                    waiter_name = order.notes.split("Created by:")[1].split("|")[0].strip()
                except:
                    pass
            
            order_list.append({
                'id': order.id,
                'order_number': order.order_number,
                'total_amount': float(order.total_amount),
                'created_at': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'waiter_name': waiter_name,
                'table_number': order.table.table_number if order.table else 'N/A',
                'items_count': order.order_items.count()
            })
        
        return jsonify({
            'success': True,
            'orders': order_list
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@pos.route('/check_report_generation_permission')
@login_required
def check_report_generation_permission():
    """Check if cashier can generate daily report (no unpaid waiter orders)"""
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Only cashiers can generate reports'})
    
    try:
        # Check for unpaid waiter orders
        unpaid_waiter_orders = Order.query.filter(
            Order.assigned_cashier_id == current_user.id,
            Order.notes.like('%[WAITER ORDER]%'),
            Order.status == OrderStatus.PENDING
        ).count()
        
        can_generate = unpaid_waiter_orders == 0
        
        return jsonify({
            'success': True,
            'can_generate_report': can_generate,
            'unpaid_waiter_orders': unpaid_waiter_orders,
            'reason': 'Can generate report' if can_generate else f'Cannot generate report: {unpaid_waiter_orders} unpaid waiter orders must be processed first'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@pos.route('/mark_daily_report_printed', methods=['POST'])
@login_required
def mark_daily_report_printed():
    """
    MULTI-CASHIER SOLUTION: Mark daily report as printed for THIS cashier
    Each cashier has their own daily report requirement
    """
    if current_user.role.name != 'CASHIER':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    try:
        today = datetime.utcnow().date()
        cashier_id = current_user.id
        cashier_name = current_user.get_full_name()
        
        # Get or create session for THIS cashier TODAY
        session = CashierSession.get_or_create_today_session(cashier_id)
        if session and not session.branch_id:
            session.branch_id = current_user.branch_id
        
        # Check if report was already printed today to avoid duplicate audit logs
        was_already_printed = session.daily_report_printed
        
        session.mark_report_printed()
        
        # Create audit log entry only if this is the first time marking as printed today
        if not was_already_printed:
            audit_log = AuditLog(
                user_id=current_user.id,
                action='DAILY_REPORT_MARKED',
                description=f'Cashier {cashier_name} manually marked daily report as printed for {today.strftime("%Y-%m-%d")}',
                ip_address=request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR'))
            )
            db.session.add(audit_log)
            db.session.commit()
        
        # Debug session info
        from flask import session as flask_session
        browser_session_id = flask_session.get('_id', 'No session ID')
        
        print(f"REPORT PRINTED DEBUG:")
        print(f"  Cashier: {cashier_name} (ID: {cashier_id})")
        print(f"  Browser Session: {browser_session_id}")
        print(f"  Cashier Session: {session.session_id}")
        print(f"  Date: {today}")
        print(f"  Report Time: {session.report_printed_at}")
        print(f"  Audit logged: {not was_already_printed}")
        
        return jsonify({
            'success': True,
            'message': f'Daily report marked as printed for {cashier_name}',
            'cashier_name': cashier_name,
            'date': today.isoformat(),
            'session_id': session.session_id,
            'browser_session_id': browser_session_id
        })
            
    except Exception as e:
        print(f"ERROR marking report printed for cashier {current_user.id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@pos.route('/orders')
@login_required
def orders():
    # Allow both cashiers and waiters to access orders from their branch
    if current_user.role not in [UserRole.CASHIER, UserRole.WAITER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        flash('Access denied. POS privileges required.', 'error')
        return redirect(url_for('pos.index'))
    
    # Get filter parameters
    table_id = request.args.get('table_id', '')
    service_type = request.args.get('service_type', '')
    delivery_company = request.args.get('delivery_company', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Build query based on user role and branch isolation
    if current_user.role == UserRole.SUPER_USER:
        # Super users can see all orders
        query = Order.query
    elif current_user.role == UserRole.BRANCH_ADMIN:
        # Branch admins can see all orders in their branch
        query = Order.query.filter_by(branch_id=current_user.branch_id)
    elif current_user.role == UserRole.CASHIER:
        # Cashiers can see orders they created + orders assigned to them by waiters
        query = Order.query.filter(
            db.or_(
                Order.cashier_id == current_user.id,  # Orders they created
                Order.assigned_cashier_id == current_user.id  # Orders assigned to them
            )
        )
    elif current_user.role == UserRole.WAITER:
        # Waiters can only see orders they created themselves
        query = Order.query.filter_by(cashier_id=current_user.id, branch_id=current_user.branch_id)
    else:
        # Fallback - should not reach here due to earlier check
        query = Order.query.filter_by(cashier_id=current_user.id)
    
    # Apply filters
    if table_id:
        query = query.filter(Order.table_id == table_id)
    if service_type:
        # Convert string to enum for filtering
        try:
            service_enum = ServiceType(service_type)
            query = query.filter(Order.service_type == service_enum)
        except ValueError:
            # Invalid service type, skip filtering
            pass
    if delivery_company:
        # Filter by delivery company using the new model
        from app.models import DeliveryCompany
        delivery_company_obj = DeliveryCompany.query.filter_by(value=delivery_company).first()
        if delivery_company_obj:
            query = query.filter(Order.delivery_company_id == delivery_company_obj.id)
    if date_from:
        query = query.filter(Order.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        query = query.filter(Order.created_at <= datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    
    # Get paginated orders
    user_orders = query.order_by(Order.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    
    # Get tables for filter
    tables = Table.query.filter_by(is_active=True).all()
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        orders_data = []
        for order in user_orders.items:
            # Count regular items (excluding special items)
            regular_items_count = sum(1 for item in order.order_items if 'طلبات خاصة' not in item.menu_item.name)
            
            # Get delivery company name safely
            delivery_company_name = None
            if order.delivery_company_id and order.delivery_company_info:
                delivery_company_name = order.delivery_company_info.name
            
            # Get creator information
            creator = User.query.get(order.cashier_id)
            creator_name = creator.get_full_name() if creator else 'Unknown'
            creator_role = creator.role.value if creator else 'unknown'
            
            # Check if this is a waiter order by looking at the notes
            is_waiter_order = order.notes and '[WAITER ORDER]' in order.notes
            
            orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'table_number': order.table.table_number if order.table else 'N/A',
                'total_amount': float(order.total_amount),
                'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
                'service_type': order.service_type.value if order.service_type else 'on_table',
                'delivery_company': delivery_company_name,
                'regular_items_count': regular_items_count,
                'creator_name': creator_name,
                'creator_role': creator_role,
                'is_waiter_order': is_waiter_order,
                'notes': order.notes,
                'status': order.status.value if order.status else 'pending',
                'paid_at': order.paid_at.strftime('%Y-%m-%d %H:%M') if order.paid_at else None,
                'can_mark_paid': (current_user.role in [UserRole.CASHIER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER] 
                                 and order.status == OrderStatus.PENDING),
                'can_edit': (current_user.role == UserRole.CASHIER and 
                           (order.cashier_id == current_user.id or order.assigned_cashier_id == current_user.id) and
                           (order.status == OrderStatus.PENDING or 
                            (order.status == OrderStatus.PAID and 
                             (order.service_type in [ServiceType.DELIVERY, ServiceType.TAKE_AWAY] or 
                              order.payment_method == PaymentMethod.CARD)))),
                'is_edited': order.edit_count > 0 if order.edit_count else False,
                'edit_count': order.edit_count or 0,
                'last_edited_at': order.last_edited_at.strftime('%Y-%m-%d %H:%M') if order.last_edited_at else None,
                'last_edited_by': User.query.get(order.last_edited_by).get_full_name() if order.last_edited_by else None
            })
        
        return jsonify({
            'success': True,
            'orders': orders_data,
            'pagination': {
                'page': user_orders.page,
                'pages': user_orders.pages,
                'per_page': user_orders.per_page,
                'total': user_orders.total,
                'has_prev': user_orders.has_prev,
                'has_next': user_orders.has_next,
                'prev_num': user_orders.prev_num,
                'next_num': user_orders.next_num
            }
        })
    
    return render_template('pos/orders.html', orders=user_orders, tables=tables, filters={
        'table_id': table_id,
        'service_type': service_type,
        'delivery_company': delivery_company,
        'date_from': date_from,
        'date_to': date_to
    })

@pos.route('/get_order_for_editing/<int:order_id>')
@login_required
def get_order_for_editing(order_id):
    """Get order details for editing (cashiers only)"""
    if current_user.role != UserRole.CASHIER:
        return jsonify({'success': False, 'message': 'Access denied. Cashier privileges required.'})
    
    try:
        # Get the order and verify cashier can edit it
        order = Order.query.filter_by(id=order_id).first()
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'})
        
        # Check if cashier can edit this order (must be assigned to them or created by them)
        if order.cashier_id != current_user.id and order.assigned_cashier_id != current_user.id:
            return jsonify({'success': False, 'message': 'You can only edit orders assigned to you'})
        
        # Check if order can be edited based on status and service type
        can_edit_paid = (order.service_type in [ServiceType.DELIVERY, ServiceType.TAKE_AWAY] or 
                        order.payment_method == PaymentMethod.CARD)
        
        if order.status == OrderStatus.PENDING:
            # Pending orders can always be edited (existing logic)
            pass
        elif order.status == OrderStatus.PAID and can_edit_paid:
            # Paid orders can be edited only for delivery, takeaway, or card payment
            # PIN verification will be handled on the frontend
            pass
        else:
            # For on-table orders that are paid, or other statuses
            if order.service_type == ServiceType.ON_TABLE and order.status == OrderStatus.PAID:
                return jsonify({'success': False, 'message': 'Paid on-table orders cannot be edited'})
            else:
                return jsonify({'success': False, 'message': 'Only pending orders and paid delivery/takeaway/card payment orders can be edited'})
        
        # Get order items
        order_items = []
        for item in order.order_items:
            # Parse special items/modifiers from notes field
            special_items = []
            notes_text = item.notes or ''
            
            # Parse modifiers from notes (format: "modifier1, modifier2, 2x modifier3")
            if notes_text and not notes_text.startswith('Custom Price:'):
                # Split by comma and parse each modifier
                modifiers = [mod.strip() for mod in notes_text.split(',') if mod.strip()]
                for modifier in modifiers:
                    # Check if modifier has quantity (e.g., "2x modifier_name")
                    if 'x ' in modifier:
                        parts = modifier.split('x ', 1)
                        if len(parts) == 2 and parts[0].strip().isdigit():
                            qty = int(parts[0].strip())
                            name = parts[1].strip()
                        else:
                            qty = 1
                            name = modifier
                    else:
                        qty = 1
                        name = modifier
                    
                    special_items.append({
                        'name': name,
                        'quantity': qty
                    })
            
            # If we have special items from notes, clear special_requests to avoid duplication
            # Only use special_requests if no special items were parsed from notes
            special_requests_text = item.special_requests or '' if not special_items else ''
            
            order_items.append({
                'id': item.id,
                'menu_item_id': item.menu_item_id,
                'menu_item_name': item.menu_item.name,
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total_price': float(item.total_price),
                'special_requests': special_requests_text,
                'notes': notes_text,
                'special_items': special_items,  # Include parsed special items
                'is_new': item.is_new or False,
                'is_deleted': item.is_deleted or False
            })
        
        return jsonify({
            'success': True,
            'order': {
                'id': order.id,
                'order_number': order.order_number,
                'total_amount': float(order.total_amount),
                'items': order_items,
                'table_number': order.table.table_number if order.table else None,
                'service_type': order.service_type.value if order.service_type else None
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@pos.route('/get_menu_items_for_editing')
@login_required
def get_menu_items_for_editing():
    """Get menu items for order editing"""
    if current_user.role != UserRole.CASHIER:
        return jsonify({'success': False, 'message': 'Access denied. Cashier privileges required.'})
    
    try:
        # Get special requests category
        special_category = Category.query.filter_by(
            branch_id=current_user.branch_id,
            name='طلبات خاصة',
            is_active=True
        ).first()
        
        # Get regular categories (exclude special category)
        categories = Category.query.filter_by(
            branch_id=current_user.branch_id, 
            is_active=True
        ).filter(
            Category.name != 'طلبات خاصة'
        ).all()
        
        # Get regular menu items (exclude special category items)
        menu_items_query = MenuItem.query.filter_by(
            branch_id=current_user.branch_id, 
            is_active=True
        )
        if special_category:
            menu_items_query = menu_items_query.filter(MenuItem.category_id != special_category.id)
        menu_items = menu_items_query.all()
        
        # Get special items from special category
        special_items = []
        if special_category:
            special_items = MenuItem.query.filter_by(
                branch_id=current_user.branch_id,
                category_id=special_category.id,
                is_active=True
            ).all()
        
        # Format categories
        categories_data = []
        for category in categories:
            categories_data.append({
                'id': category.id,
                'name': category.name
            })
        
        # Format menu items
        items_data = []
        for item in menu_items:
            items_data.append({
                'id': item.id,
                'name': item.name,
                'price': float(item.price),
                'category_id': item.category_id
            })
        
        # Format special items
        special_items_data = []
        for item in special_items:
            special_items_data.append({
                'id': item.id,
                'name': item.name,
                'price': float(item.price)
            })
        
        return jsonify({
            'success': True,
            'categories': categories_data,
            'items': items_data,
            'special_items': special_items_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@pos.route('/save_order_changes', methods=['POST'])
@login_required
def save_order_changes():
    """Save changes to an order (cashiers only)"""
    if current_user.role != UserRole.CASHIER:
        return jsonify({'success': False, 'message': 'Access denied. Cashier privileges required.'})
    
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        items = data.get('items', [])
        original_total = data.get('original_total', 0)
        
        # Get the order
        order = Order.query.filter_by(id=order_id).first()
        if not order:
            return jsonify({'success': False, 'message': 'Order not found'})
        
        # Verify cashier can edit this order
        if order.cashier_id != current_user.id and order.assigned_cashier_id != current_user.id:
            return jsonify({'success': False, 'message': 'You can only edit orders assigned to you'})
        
        # Check if order can be edited based on status and service type
        can_edit_paid = (order.service_type in [ServiceType.DELIVERY, ServiceType.TAKE_AWAY] or 
                        order.payment_method == PaymentMethod.CARD)
        
        if order.status == OrderStatus.PENDING:
            # Pending orders can always be edited (existing logic)
            pass
        elif order.status == OrderStatus.PAID and can_edit_paid:
            # Paid orders can be edited only for delivery, takeaway, or card payment
            # PIN verification should have been done on the frontend
            pass
        else:
            # For on-table orders that are paid, or other statuses
            if order.service_type == ServiceType.ON_TABLE and order.status == OrderStatus.PAID:
                return jsonify({'success': False, 'message': 'Paid on-table orders cannot be edited'})
            else:
                return jsonify({'success': False, 'message': 'Only pending orders and paid delivery/takeaway/card payment orders can be edited'})
        
        # Process items with proper edit tracking
        new_total = 0
        existing_items = {item.id: item for item in order.order_items}
        processed_item_ids = set()
        
        for item_data in items:
            item_id = item_data.get('id')
            is_new = item_data.get('is_new', False)
            is_deleted = item_data.get('is_deleted', False)
            
            if item_id and item_id in existing_items:
                # Update existing item
                existing_item = existing_items[item_id]
                existing_item.quantity = item_data['quantity']
                existing_item.unit_price = item_data['unit_price']
                existing_item.total_price = item_data['total_price']
                existing_item.special_requests = item_data.get('special_requests', '')
                
                # Handle notes field (preserve existing special items from notes)
                # If there are special_items in the frontend data, convert them back to notes format
                if 'special_items' in item_data and item_data['special_items']:
                    # Convert special_items array back to notes format
                    special_items_notes = []
                    for special_item in item_data['special_items']:
                        if special_item['quantity'] > 1:
                            special_items_notes.append(f"{special_item['quantity']}x {special_item['name']}")
                        else:
                            special_items_notes.append(special_item['name'])
                    existing_item.notes = ', '.join(special_items_notes)
                elif item_data.get('notes'):
                    # Preserve existing notes if no special_items array
                    existing_item.notes = item_data.get('notes', '')
                
                existing_item.is_deleted = is_deleted
                processed_item_ids.add(item_id)
                
                # Only add to total if not deleted
                if not is_deleted:
                    new_total += item_data['total_price']
                    
            elif is_new and not is_deleted:
                # Create new item (marked as new)
                # Handle notes field for new items
                notes_text = ''
                if 'special_items' in item_data and item_data['special_items']:
                    # Convert special_items array to notes format
                    special_items_notes = []
                    for special_item in item_data['special_items']:
                        if special_item['quantity'] > 1:
                            special_items_notes.append(f"{special_item['quantity']}x {special_item['name']}")
                        else:
                            special_items_notes.append(special_item['name'])
                    notes_text = ', '.join(special_items_notes)
                elif item_data.get('notes'):
                    notes_text = item_data.get('notes', '')
                
                order_item = OrderItem(
                    order_id=order_id,
                    menu_item_id=item_data['menu_item_id'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_price=item_data['total_price'],
                    special_requests=item_data.get('special_requests', ''),
                    notes=notes_text,
                    is_new=True,
                    is_deleted=False
                )
                db.session.add(order_item)
                new_total += item_data['total_price']
        
        # Mark any items not in the update as deleted (but don't actually delete them)
        for item_id, existing_item in existing_items.items():
            if item_id not in processed_item_ids:
                existing_item.is_deleted = True
        
        # Update order total and mark as edited
        order.total_amount = new_total
        order.last_edited_at = datetime.utcnow()
        order.last_edited_by = current_user.id
        order.edit_count = (order.edit_count or 0) + 1
        
        # Add edit history record
        edit_history = OrderEditHistory(
            order_id=order_id,
            edited_by=current_user.id,
            edited_at=datetime.utcnow(),
            original_total=original_total,
            new_total=new_total,
            changes_summary=f"Order edited by {current_user.get_full_name()}"
        )
        db.session.add(edit_history)
        
        # Create audit log entry for order edit
        audit_log = AuditLog(
            user_id=current_user.id,
            action='ORDER_EDITED',
            description=f'Order #{order.order_number} edited by {current_user.get_full_name()}. Total changed from QAR {original_total:.2f} to QAR {new_total:.2f}. Table: {order.table.table_number if order.table else "N/A"}',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        db.session.add(audit_log)
        
        db.session.commit()
        
        # Emit socket event to notify waiters about order edit
        if order.table_id and current_user.role == UserRole.CASHIER:
            socketio.emit('order_edited_by_cashier', {
                'order_id': order.id,
                'order_number': order.order_number,
                'table_id': order.table_id,
                'table_number': order.table.table_number if order.table else None,
                'branch_id': order.branch_id,
                'editor_name': current_user.get_full_name(),
                'edit_summary': f"Order total changed from QAR {original_total:.2f} to QAR {new_total:.2f}",
                'new_total': new_total,
                'edit_count': order.edit_count,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'branch_{order.branch_id}')
        
        return jsonify({
            'success': True,
            'message': 'Order updated successfully',
            'new_total': new_total,
            'edit_timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@pos.route('/waiter_requests')
@login_required
def waiter_requests():
    """Waiter requests interface for cashiers - shows only waiter orders"""
    # Only allow cashiers and above to access waiter requests
    if current_user.role not in [UserRole.CASHIER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        flash('Access denied. Cashier privileges required.', 'error')
        return redirect(url_for('pos.index'))
    
    # Handle AJAX requests for loading orders
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')
        status_filter = request.args.get('status_filter', 'pending')
        
        # Build query for waiter orders only (exclude cleared orders)
        if current_user.role == UserRole.SUPER_USER:
            query = Order.query.filter(
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        elif current_user.role == UserRole.CASHIER:
            # Cashiers only see orders assigned to them specifically
            query = Order.query.filter(
                Order.assigned_cashier_id == current_user.id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        else:
            # Branch admins see all waiter orders in their branch
            query = Order.query.filter(
                Order.branch_id == current_user.branch_id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        
        # Apply status filter - default to pending only for waiter requests
        if status_filter == 'paid':
            query = query.filter(Order.status == OrderStatus.PAID)
        elif status_filter == 'all':
            # Only show all if explicitly requested
            pass
        else:
            # Default: only show pending orders (paid orders should not appear)
            query = query.filter(Order.status == OrderStatus.PENDING)
        
        # Apply sorting
        if sort_by == 'created_at':
            if sort_order == 'desc':
                query = query.order_by(Order.created_at.desc())
            else:
                query = query.order_by(Order.created_at.asc())
        elif sort_by == 'total_amount':
            if sort_order == 'desc':
                query = query.order_by(Order.total_amount.desc())
            else:
                query = query.order_by(Order.total_amount.asc())
        elif sort_by == 'table_number':
            query = query.join(Table).order_by(
                Table.table_number.desc() if sort_order == 'desc' else Table.table_number.asc()
            )
        
        # Paginate results
        orders_paginated = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Format orders data
        orders_data = []
        for order in orders_paginated.items:
            # Get creator information
            creator = User.query.get(order.cashier_id)
            creator_name = creator.get_full_name() if creator else 'Unknown'
            
            # Get items count
            items_count = order.order_items.count()
            
            orders_data.append({
                'id': order.id,
                'order_number': order.order_number,
                'table_number': order.table.table_number if order.table else 'N/A',
                'total_amount': float(order.total_amount),
                'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
                'created_at_relative': order.created_at.strftime('%H:%M'),
                'status': order.status.value,
                'paid_at': order.paid_at.strftime('%Y-%m-%d %H:%M') if order.paid_at else None,
                'creator_name': creator_name,
                'items_count': items_count,
                'can_mark_paid': order.status == OrderStatus.PENDING,
                'can_edit': (current_user.role == UserRole.CASHIER and 
                           (order.cashier_id == current_user.id or order.assigned_cashier_id == current_user.id) and
                           order.status == OrderStatus.PENDING),  # Only allow editing pending on-table orders
                'edit_count': order.edit_count or 0,
                'last_edited_at': order.last_edited_at.strftime('%Y-%m-%d %H:%M') if order.last_edited_at else None,
                'last_edited_by': User.query.get(order.last_edited_by).get_full_name() if order.last_edited_by else None,
                'is_edited': (order.edit_count and order.edit_count > 0)
            })
        
        # Get statistics (exclude cleared orders)
        if current_user.role == UserRole.SUPER_USER:
            stats_query = Order.query.filter(
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        elif current_user.role == UserRole.CASHIER:
            # Cashiers only see statistics for orders assigned to them
            stats_query = Order.query.filter(
                Order.assigned_cashier_id == current_user.id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        else:
            # Branch admins see all waiter order statistics in their branch
            stats_query = Order.query.filter(
                Order.branch_id == current_user.branch_id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            )
        
        total_orders = stats_query.count()
        paid_orders = stats_query.filter(Order.status == OrderStatus.PAID).count()
        pending_orders = stats_query.filter(Order.status == OrderStatus.PENDING).count()
        
        return jsonify({
            'success': True,
            'orders': orders_data,
            'pagination': {
                'page': orders_paginated.page,
                'pages': orders_paginated.pages,
                'per_page': orders_paginated.per_page,
                'total': orders_paginated.total,
                'has_next': orders_paginated.has_next,
                'has_prev': orders_paginated.has_prev
            },
            'stats': {
                'total': total_orders,
                'paid': paid_orders,
                'pending': pending_orders
            }
        })
    
    # Render template for regular requests
    return render_template('pos/waiter_requests.html')

@pos.route('/clear_waiter_requests', methods=['POST'])
@login_required
def clear_waiter_requests():
    """Clear all paid waiter orders - cashiers only with race condition protection"""
    if current_user.role not in [UserRole.CASHIER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    try:
        current_app.logger.info(f"Clear waiter requests called by {current_user.get_full_name()}")
        # Get all waiter orders for this user (only non-cleared ones)
        if current_user.role == UserRole.SUPER_USER:
            waiter_orders = Order.query.filter(
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            ).all()
        elif current_user.role == UserRole.CASHIER:
            # Cashiers only clear orders assigned to them
            waiter_orders = Order.query.filter(
                Order.assigned_cashier_id == current_user.id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            ).all()
        else:
            # Branch admins clear all waiter orders in their branch
            waiter_orders = Order.query.filter(
                Order.branch_id == current_user.branch_id,
                Order.notes.contains('[WAITER ORDER]'),
                Order.cleared_from_waiter_requests == False
            ).all()
        
        current_app.logger.info(f"Found {len(waiter_orders)} waiter orders")
        
        # Get list of PAID orders to clear (allow clearing even with pending orders)
        paid_orders_to_clear = [order for order in waiter_orders if order.status == OrderStatus.PAID]
        pending_orders = [order for order in waiter_orders if order.status == OrderStatus.PENDING]
        
        if not paid_orders_to_clear:
            current_app.logger.info("No paid orders to clear")
            return jsonify({
                'success': False,
                'message': 'No paid orders to clear'
            }), 400
        
        # Mark paid orders as cleared from waiter requests (don't delete from database)
        paid_orders_count = 0
        orders_to_clear_ids = []
        current_app.logger.info(f"Starting to clear {len(paid_orders_to_clear)} paid orders from waiter requests")
        
        for order in paid_orders_to_clear:
            current_app.logger.info(f"Clearing order {order.id} from waiter requests")
            order.cleared_from_waiter_requests = True
            orders_to_clear_ids.append(order.id)
            paid_orders_count += 1
        
        # Commit the transaction
        current_app.logger.info(f"Committing clearing of {paid_orders_count} orders")
        db.session.commit()
        current_app.logger.info("Commit successful")
        
        # Emit socket event for real-time updates (after successful commit)
        socketio.emit('waiter_requests_cleared', {
            'cleared_count': paid_orders_count,
            'cleared_order_ids': orders_to_clear_ids,
            'pending_count': len(pending_orders),
            'branch_id': current_user.branch_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'branch_{current_user.branch_id}')
        
        # Log the clearing action
        current_app.logger.info(f"Cashier {current_user.get_full_name()} cleared {paid_orders_count} paid waiter orders")
        
        # Create success message
        if len(pending_orders) > 0:
            message = f'Successfully cleared {paid_orders_count} paid orders. {len(pending_orders)} pending orders remain.'
        else:
            message = f'Successfully cleared {paid_orders_count} paid orders'
        
        return jsonify({
            'success': True,
            'message': message,
            'cleared_count': paid_orders_count,
            'pending_count': len(pending_orders)
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing waiter requests: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error clearing orders: {str(e)}'
        }), 500

@pos.route('/table_management')
@login_required
def table_management():
    """Table management interface for waiters"""
    # Only allow waiters and above to access table management
    if current_user.role not in [UserRole.WAITER, UserRole.CASHIER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
        flash('Access denied. Waiter privileges required.', 'error')
        return redirect(url_for('pos.index'))
    
    # Get all tables for the current branch
    tables = Table.query.filter_by(branch_id=current_user.branch_id).order_by(Table.table_number).all()
    
    # Get table statuses with recent orders
    table_data = []
    for table in tables:
        # Get the most recent order for this table
        recent_order = Order.query.filter_by(
            table_id=table.id,
            branch_id=current_user.branch_id
        ).order_by(Order.created_at.desc()).first()
        
        # Determine table status
        is_busy = False
        order_info = None
        
        if recent_order:
            # Check if there's a recent pending or active order (within last 4 hours)
            from datetime import datetime, timedelta
            four_hours_ago = datetime.utcnow() - timedelta(hours=4)
            
            # Table is only busy if there's a PENDING order (not PAID)
            # Once cashier marks order as PAID, table becomes free for new orders
            if (recent_order.created_at > four_hours_ago and 
                recent_order.status == OrderStatus.PENDING):
                is_busy = True
                order_info = {
                    'id': recent_order.id,
                    'order_number': recent_order.order_number,
                    'total_amount': float(recent_order.total_amount),
                    'created_at': recent_order.created_at.strftime('%H:%M'),
                    'status': recent_order.status.value,
                    'items_count': recent_order.order_items.count(),
                    'waiter_name': recent_order.cashier.get_full_name() if recent_order.cashier else 'Unknown'
                }
        
        table_data.append({
            'table': table,
            'is_busy': is_busy,
            'order_info': order_info
        })
    
    # Get menu categories and items for the modal POS interface
    categories = Category.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Category.order_index).all()
    
    return render_template('pos/table_management.html', table_data=table_data, categories=categories)

@pos.route('/create_order', methods=['POST'])
@login_required
def create_order():
    try:
        # Get order data from request
        table_id = request.json.get('table_id')
        customer_id = request.json.get('customer_id')
        items = request.json.get('items', [])
        service_type = request.json.get('service_type', 'on_table')
        delivery_company_id = request.json.get('delivery_company_id')
        is_adding_items = request.json.get('is_adding_items', False)  # Flag to indicate adding to existing order
        
        # Debug logging
        print(f"DEBUG: is_adding_items = {is_adding_items}")
        print(f"DEBUG: existing_order_id = {request.json.get('existing_order_id')}")
        print(f"DEBUG: table_id = {table_id}")
        
        if not items:
            return jsonify({'success': False, 'message': 'No items in order'}), 400
        
        # Check if this is adding items to an existing order
        existing_order = None
        existing_order_id = request.json.get('existing_order_id')
        
        if is_adding_items:
            if existing_order_id:
                # Use the specific order ID provided
                existing_order = Order.query.filter_by(
                    id=existing_order_id,
                    branch_id=current_user.branch_id,
                    status=OrderStatus.PENDING
                ).first()
            elif table_id:
                # Fallback: Find the existing PENDING order for this table
                existing_order = Order.query.filter_by(
                    table_id=table_id,
                    branch_id=current_user.branch_id,
                    status=OrderStatus.PENDING
                ).order_by(Order.created_at.desc()).first()
            
            if not existing_order:
                return jsonify({'success': False, 'message': 'No existing order found to update'}), 400
        
        # Calculate totals
        from decimal import Decimal
        total_amount = Decimal('0')
        order_items = []
        
        for item_data in items:
            # Handle custom price items (like Falafel Hab and Special Order)
            if item_data.get('id') in ['falafel_hab_custom', 'special_order_custom'] or item_data.get('isCustomPrice'):
                # For custom price items, use the provided price instead of menu price
                custom_price = Decimal(str(item_data.get('price', 0)))
                quantity = item_data['quantity']
                item_total = custom_price * quantity
                total_amount += item_total
                
                # Find the actual menu item
                item_name = item_data.get('name', '')
                if item_name == 'Falafel Hab':
                    menu_item = MenuItem.query.filter_by(name='Falafel Hab').first()
                    if not menu_item:
                        return jsonify({'success': False, 'message': 'Falafel Hab item not found in menu'}), 400
                elif item_name == 'special order':
                    menu_item = MenuItem.query.filter_by(name='special order').first()
                    if not menu_item:
                        return jsonify({'success': False, 'message': 'Special order item not found in menu'}), 400
                else:
                    return jsonify({'success': False, 'message': f'Unknown custom price item: {item_name}'}), 400
                
                # Handle modifiers for custom price items
                modifiers_text = ""
                if 'modifiers' in item_data and item_data['modifiers']:
                    modifier_list = []
                    for modifier in item_data['modifiers']:
                        modifier_qty = modifier.get('quantity', 1)
                        modifier_name = modifier.get('name', '')
                        if modifier_qty > 1:
                            modifier_list.append(f"{modifier_qty}x {modifier_name}")
                        else:
                            modifier_list.append(modifier_name)
                    modifiers_text = ", ".join(modifier_list)
                
                # Add note about custom price
                custom_price_note = f"Custom Price: {custom_price:.2f} QAR"
                if modifiers_text:
                    modifiers_text = f"{custom_price_note}, {modifiers_text}"
                else:
                    modifiers_text = custom_price_note
                
                order_item = OrderItem(
                    menu_item_id=menu_item.id,
                    quantity=quantity,
                    unit_price=custom_price,  # Use custom price
                    total_price=item_total,
                    notes=modifiers_text
                )
                order_items.append(order_item)
                continue
            
            # Handle regular menu items
            menu_item = MenuItem.query.get(item_data['id'])
            if not menu_item:
                return jsonify({'success': False, 'message': f'Item not found: {item_data["id"]}'}), 400
            
            quantity = item_data['quantity']
            item_total = menu_item.price * quantity
            total_amount += item_total
            
            # Handle modifiers - store them in notes field
            modifiers_text = ""
            if 'modifiers' in item_data and item_data['modifiers']:
                modifier_list = []
                for modifier in item_data['modifiers']:
                    modifier_qty = modifier.get('quantity', 1)
                    modifier_name = modifier.get('name', '')
                    if modifier_qty > 1:
                        modifier_list.append(f"{modifier_qty}x {modifier_name}")
                    else:
                        modifier_list.append(modifier_name)
                modifiers_text = ", ".join(modifier_list)
            
            order_item = OrderItem(
                menu_item_id=menu_item.id,
                quantity=quantity,
                unit_price=menu_item.price,
                total_price=item_total,
                notes=modifiers_text if modifiers_text else None
            )
            order_items.append(order_item)
        
        # Generate unique order number
        order_number = generate_order_number()
        
        # Create order with proper tracking of who created it
        # For waiters, we'll add a note to indicate the order came from a waiter
        order_notes = request.json.get('notes', '')
        assigned_cashier_id = request.json.get('assigned_cashier_id')
        
        if current_user.role == UserRole.WAITER:
            # For waiters, check if they have an assigned cashier from database
            assignment = WaiterCashierAssignment.get_assignment_for_waiter(
                current_user.id, current_user.branch_id
            )
            
            if assignment and assignment.assigned_cashier:
                # Use the assigned cashier from database
                assigned_cashier_id = assignment.assigned_cashier_id
                waiter_note = f"[WAITER ORDER] Created by: {current_user.get_full_name()} | Assigned to: {assignment.assigned_cashier.get_full_name()} (Admin Assigned)"
            else:
                # No admin assignment - prevent order creation
                return jsonify({
                    'success': False,
                    'message': 'Cannot create order. Please ask an admin to assign you to a cashier using their PIN code.',
                    'error_type': 'no_cashier_assignment'
                })
                        
            order_notes = f"{waiter_note}\n{order_notes}" if order_notes else waiter_note
            # Waiter orders start as PENDING (need cashier to mark as paid)
            order_status = OrderStatus.PENDING
        else:
            # Cashier orders are immediately marked as PAID
            order_status = OrderStatus.PAID
        
        service_type_enum = ServiceType(service_type) if service_type else ServiceType.ON_TABLE
        
        # Handle existing order update vs new order creation
        if existing_order:
            # UPDATE EXISTING ORDER - Add new items to existing order
            print(f"DEBUG: UPDATING existing order #{existing_order.order_number}")
            order = existing_order
            
            # Add new total to existing total
            order.total_amount += total_amount
            
            # Add new items to existing order
            for item in order_items:
                order.order_items.append(item)
            
            # Update notes to indicate items were added
            local_time = TimezoneManager.get_current_time()
            add_note = f"\n[ITEMS ADDED] by {current_user.get_full_name()} at {local_time.strftime('%Y-%m-%d %H:%M:%S')}"
            order.notes = (order.notes or '') + add_note
            
            # Store original item count for future reference
            if '[ORIGINAL_ITEMS_COUNT]' not in (order.notes or ''):
                original_count = order.order_items.count() - len(order_items)  # Subtract newly added items
                order.notes += f"\n[ORIGINAL_ITEMS_COUNT:{original_count}]"
            
            # Keep the same order number and assigned cashier
            order_number = order.order_number
            assigned_cashier_id = order.assigned_cashier_id
            
            # Save updated order
            db.session.commit()
            
            is_new_order = False
        else:
            # CREATE NEW ORDER
            print(f"DEBUG: CREATING new order (is_adding_items={is_adding_items}, existing_order_found={existing_order is not None})")
            
            # Get next counter number for this branch
            order_counter = OrderCounter.get_next_counter(current_user.branch_id)
            
            order = Order(
                order_number=order_number,
                order_counter=order_counter,  # Add sequential counter
                total_amount=total_amount,
                cashier_id=current_user.id,  # Track who created the order (cashier or waiter)
                assigned_cashier_id=assigned_cashier_id,  # Which cashier waiter assigned order to
                branch_id=current_user.branch_id,  # Add branch_id from current user
                table_id=table_id,
                customer_id=customer_id,
                service_type=service_type_enum,
                delivery_company_id=delivery_company_id,
                notes=order_notes,
                status=order_status  # Set status based on user role
            )
            # Set paid_at timestamp in UTC for database storage, but use local time for user display
            order.paid_at = datetime.utcnow() if order_status == OrderStatus.PAID else None
            
            # Add order items
            for item in order_items:
                order.order_items.append(item)
            
            # Save to database
            db.session.add(order)
            db.session.commit()
            
            is_new_order = True
        
        # MULTI-CASHIER: Ensure session exists for tracking (but don't fail if it doesn't)
        # Only create sessions for cashiers, not waiters
        if current_user.role == UserRole.CASHIER:
            try:
                # Create session if it doesn't exist (for report tracking)
                session = CashierSession.get_or_create_today_session(current_user.id)
                
                # Update order count for this session
                today_order_count = Order.query.filter(
                    Order.cashier_id == current_user.id,
                    func.date(Order.created_at) == datetime.utcnow().date()
                ).count()
                session.update_order_count(today_order_count)
                
                # Debug session info
                from flask import session as flask_session
                browser_session_id = flask_session.get('_id', 'No session ID')
                
                print(f"ORDER CREATED DEBUG:")
                print(f"  Cashier: {current_user.get_full_name()} (ID: {current_user.id})")
                print(f"  Browser Session: {browser_session_id}")
                print(f"  Cashier Session: {session.session_id}")
                print(f"  Order Number: {order_number}")
                print(f"  Today's Order Count: {today_order_count}")
                print(f"  Report Printed: {session.daily_report_printed}")
                
            except Exception as session_error:
                # Don't fail the order creation if session update fails
                print(f"Session tracking error (order still created): {session_error}")
        
        # Check if there's a return_to parameter for redirection
        return_to = request.json.get('return_to')
        
        # Emit socket event for real-time order updates
        if is_new_order:
            # WAITER ISOLATION FIX: Different emission strategy based on user role
            if current_user.role == UserRole.WAITER:
                # For waiter orders: Send to waiter who created it (for their own orders page)
                socketio.emit('new_order', {
                    'order_id': order.id,
                    'order_number': order_number,
                    'table_id': order.table_id,
                    'table_number': order.table.table_number if order.table else None,
                    'branch_id': order.branch_id,
                    'creator_name': current_user.get_full_name(),
                    'creator_role': current_user.role.value,
                    'total_amount': float(order.total_amount),
                    'service_type': order.service_type.value if order.service_type else 'on_table',
                    'is_waiter_order': True,
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'waiter_{current_user.id}')
                
                # ALSO send table status update to entire branch (for table management page)
                if order.table_id:
                    socketio.emit('table_status_update', {
                        'table_id': order.table_id,
                        'table_number': order.table.table_number if order.table else None,
                        'status': 'busy',
                        'order_id': order.id,
                        'order_number': order_number,
                        'branch_id': order.branch_id,
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=f'branch_{order.branch_id}')
                
                print(f"ISOLATION: Waiter order #{order_number} new_order event sent to waiter_{current_user.id}, table status update sent to branch_{order.branch_id}")
            else:
                # For cashier orders: Broadcast to entire branch (existing behavior)
                socketio.emit('new_order', {
                    'order_id': order.id,
                    'order_number': order_number,
                    'table_id': order.table_id,
                    'table_number': order.table.table_number if order.table else None,
                    'branch_id': order.branch_id,
                    'creator_name': current_user.get_full_name(),
                    'creator_role': current_user.role.value,
                    'total_amount': float(order.total_amount),
                    'service_type': order.service_type.value if order.service_type else 'on_table',
                    'is_waiter_order': False,
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'branch_{order.branch_id}')
        else:
            # Order updated event - same isolation logic as new_order
            if current_user.role == UserRole.WAITER:
                # For waiter order updates: Only notify the waiter who owns the order
                socketio.emit('order_updated', {
                    'order_id': order.id,
                    'order_number': order_number,
                    'table_id': order.table_id,
                    'table_number': order.table.table_number if order.table else None,
                    'branch_id': order.branch_id,
                    'updater_name': current_user.get_full_name(),
                    'updater_role': current_user.role.value,
                    'new_total_amount': float(order.total_amount),
                    'added_items_count': len(order_items),
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'waiter_{current_user.id}')
                
                print(f"ISOLATION: Waiter order #{order_number} update event sent only to waiter_{current_user.id}")
            else:
                # For cashier order updates: Broadcast to entire branch
                socketio.emit('order_updated', {
                    'order_id': order.id,
                    'order_number': order_number,
                    'table_id': order.table_id,
                    'table_number': order.table.table_number if order.table else None,
                    'branch_id': order.branch_id,
                    'updater_name': current_user.get_full_name(),
                    'updater_role': current_user.role.value,
                    'new_total_amount': float(order.total_amount),
                    'added_items_count': len(order_items),
                    'timestamp': datetime.utcnow().isoformat()
                }, room=f'branch_{order.branch_id}')
        
        # If this is a waiter order, emit specific waiter_request event to assigned cashier ONLY
        if current_user.role == UserRole.WAITER and assigned_cashier_id:
            # CRITICAL ISOLATION FIX: Emit to specific cashier room, NOT entire branch
            target_room = f'cashier_{assigned_cashier_id}'
            
            # Validate that assigned cashier exists and is in same branch
            assigned_cashier = User.query.get(assigned_cashier_id)
            if assigned_cashier and assigned_cashier.branch_id == current_user.branch_id and assigned_cashier.role == UserRole.CASHIER:
                if is_new_order:
                    # New waiter request
                    socketio.emit('new_waiter_request', {
                        'order_id': order.id,
                        'order_number': order_number,
                        'table_id': order.table_id,
                        'table_number': order.table.table_number if order.table else None,
                        'branch_id': order.branch_id,
                        'creator_name': current_user.get_full_name(),
                        'assigned_cashier_name': assigned_cashier.get_full_name(),
                        'total_amount': float(order.total_amount),
                        'items_count': len(order_items),
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=target_room)
                else:
                    # Order updated notification
                    socketio.emit('waiter_order_updated', {
                        'order_id': order.id,
                        'order_number': order_number,
                        'table_id': order.table_id,
                        'table_number': order.table.table_number if order.table else None,
                        'branch_id': order.branch_id,
                        'updater_name': current_user.get_full_name(),
                        'assigned_cashier_name': assigned_cashier.get_full_name(),
                        'new_total_amount': float(order.total_amount),
                        'added_items_count': len(order_items),
                        'timestamp': datetime.utcnow().isoformat()
                    }, room=target_room)
                
                print(f"ISOLATION: Waiter {'request' if is_new_order else 'update'} sent to specific cashier room: {target_room}")
            else:
                print(f"ERROR: Invalid cashier assignment - Order {order_number} not sent to any cashier")
        elif current_user.role == UserRole.WAITER and not assigned_cashier_id:
            print(f"WARNING: Waiter order {order_number} created without assigned cashier - no real-time notification sent")
        
        return jsonify({
            'success': True, 
            'message': 'Order updated successfully' if not is_new_order else 'Order created successfully',
            'order_id': order.id,
            'order_number': order_number,
            'return_to': return_to,
            'is_update': not is_new_order
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@pos.route('/mark_order_paid/<int:order_id>', methods=['POST'])
@login_required
def mark_order_paid(order_id):
    """Mark an order as paid - only cashiers and admins can do this"""
    try:
        # Check permissions
        if current_user.role not in [UserRole.CASHIER, UserRole.BRANCH_ADMIN, UserRole.SUPER_USER]:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        order = Order.query.get_or_404(order_id)
        
        # Check branch access
        if (current_user.role not in [UserRole.SUPER_USER] and 
            order.branch_id != current_user.branch_id):
            return jsonify({'success': False, 'message': 'Access denied - different branch'}), 403
        
        # Check if order is already paid
        if order.status == OrderStatus.PAID:
            return jsonify({'success': False, 'message': 'Order is already paid'}), 400
        
        # Mark as paid
        order.status = OrderStatus.PAID
        order.paid_at = datetime.utcnow()  # Store in UTC for database
        db.session.commit()
        
        # Log the action
        current_app.logger.info(f"Order {order.order_number} marked as paid by {current_user.get_full_name()}")
        
        # Emit socket event for real-time table status updates
        socketio.emit('order_paid', {
            'order_id': order.id,
            'table_id': order.table_id,
            'table_number': order.table.table_number if order.table else None,
            'branch_id': order.branch_id
        }, room=f'branch_{order.branch_id}')
        
        # ALSO emit table status update (free) for table management page
        if order.table_id:
            socketio.emit('table_status_update', {
                'table_id': order.table_id,
                'table_number': order.table.table_number if order.table else None,
                'status': 'free',
                'order_id': order.id,
                'order_number': order.order_number,
                'branch_id': order.branch_id,
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'branch_{order.branch_id}')
        
        return jsonify({
            'success': True,
            'message': 'Order marked as paid successfully',
            'paid_at': order.paid_at.strftime('%Y-%m-%d %H:%M')
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking order {order_id} as paid: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error marking order as paid: {str(e)}'
        }), 500

@pos.route('/get_delivery_companies')
@login_required
def get_delivery_companies():
    """Get active delivery companies for current user's branch"""
    try:
        # Filter by current user's branch and active status
        companies = DeliveryCompany.query.filter_by(
            branch_id=current_user.branch_id,
            is_active=True
        ).all()
        
        companies_data = []
        for company in companies:
            companies_data.append({
                'id': company.id,
                'name': company.name,
                'value': company.value,
                'icon': company.icon
            })
        
        return jsonify({
            'success': True,
            'companies': companies_data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error loading delivery companies: {str(e)}'
        }), 500

# Order status management functions removed - orders are now simply created

@pos.route('/order_details/<int:order_id>')
@login_required
@pos_access_required
def order_details(order_id):
    """View order details page (for direct access)"""
    try:
        order = Order.query.get_or_404(order_id)
        
        # Check branch access
        if not current_user.is_super_user() and order.branch_id != current_user.branch_id:
            flash('Access denied: Order not in your branch', 'error')
            return redirect(url_for('pos.waiter_requests'))
        
        return render_template('pos/order_details.html', order=order)
        
    except Exception as e:
        current_app.logger.error(f"Error loading order details page: {e}")
        flash(f'Error loading order details: {str(e)}', 'error')
        return redirect(url_for('pos.waiter_requests'))

@pos.route('/get_order_details/<int:order_id>')
@login_required
def get_order_details(order_id):
    try:
        order = Order.query.get_or_404(order_id)
        
        # Check if the current user is authorized to view this order
        # Allow: Super users, branch admins, and users from the same branch
        if (current_user.role == UserRole.SUPER_USER or 
            current_user.role == UserRole.BRANCH_ADMIN or 
            order.branch_id == current_user.branch_id):
            # Access granted
            pass
        else:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        items = []
        for item in order.order_items:
            items.append({
                'id': item.id,
                'menu_item_name': item.menu_item.name,  # Frontend expects menu_item_name
                'quantity': item.quantity,
                'price': float(item.unit_price),  # Frontend expects price
                'unit_price': float(item.unit_price),
                'total_price': float(item.total_price),
                'special_requests': item.special_requests or item.notes,  # Use special_requests field first, fallback to notes
                'is_new': item.is_new or False,  # Get from database
                'is_deleted': item.is_deleted or False  # Get from database
            })
        
        # Get delivery company name safely
        delivery_company_name = None
        if order.delivery_company_id and order.delivery_company_info:
            delivery_company_name = order.delivery_company_info.name
        
        return jsonify({
            'success': True,
            'order': {
                'id': order.id,
                'order_number': order.order_number,
                'order_counter': order.order_counter if order.order_counter else None,
                'total_amount': float(order.total_amount),
                'created_at': TimezoneManager.format_local_time(order.created_at, '%Y-%m-%d %H:%M:%S'),
                'paid_at': TimezoneManager.format_local_time(order.paid_at, '%Y-%m-%d %H:%M:%S') if order.paid_at else None,
                'table_number': order.table.table_number if order.table else None,
                'cashier_name': order.cashier.get_full_name() if order.cashier else None,
                'creator_name': order.cashier.get_full_name() if order.cashier else 'Unknown',  # Frontend expects creator_name
                'branch_name': order.branch.name if order.branch else 'Unknown',  # Frontend expects branch_name
                'service_type': order.service_type.value if order.service_type else 'on_table',
                'delivery_company': delivery_company_name,
                'status': order.status.value,
                'notes': order.notes,
                'edit_count': order.edit_count or 0,
                'last_edited_at': TimezoneManager.format_local_time(order.last_edited_at, '%Y-%m-%d %H:%M:%S') if order.last_edited_at else None,
                'last_edited_by': User.query.get(order.last_edited_by).get_full_name() if order.last_edited_by else None,
                'items': items
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error loading order details: {str(e)}'
        }), 500

@pos.route('/get_order_details_for_item/<int:item_id>')
@login_required
def get_order_details_for_item(item_id):
    # Check if the current user is authorized (admin or cashier)
    if current_user.role.name not in ['ADMIN', 'CASHIER']:
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    # Count how many orders have used this item
    order_count = db.session.query(OrderItem).filter_by(menu_item_id=item_id).count()
    
    return jsonify({
        'success': True,
        'order_count': order_count
    })

@pos.route('/get_special_ui_prefs')
@login_required
def get_special_ui_prefs():
    """Return special items UI preferences for current user and branch"""
    # Allow both cashiers and waiters to access UI preferences
    if current_user.role.name not in ['CASHIER', 'WAITER']:
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    try:
        # Get special items preferences from CashierUiSetting
        special_width_pct = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_width_pct', '100')
        special_height_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_height_px', '40')
        special_font_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_font_px', '11')
        special_spacing_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_spacing_px', '8')
        special_sidebar_width = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_sidebar_width', '100')
        
        data = {
            'special_width_pct': int(special_width_pct) if str(special_width_pct).isdigit() else 100,
            'special_height_px': int(special_height_px) if str(special_height_px).isdigit() else 40,
            'special_font_px': int(special_font_px) if str(special_font_px).isdigit() else 11,
            'special_spacing_px': int(special_spacing_px) if str(special_spacing_px).isdigit() else 8,
            'special_sidebar_width': int(special_sidebar_width) if str(special_sidebar_width).isdigit() else 100,
        }
        return jsonify({'success': True, 'data': data})
    except (OperationalError, ProgrammingError):
        # Likely new tables not yet created; create all and retry once
        db.create_all()
        try:
            special_width_pct = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_width_pct', '100')
            special_height_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_height_px', '40')
            special_font_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_font_px', '11')
            special_spacing_px = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_spacing_px', '8')
            special_sidebar_width = CashierUiSetting.get_value(current_user.id, current_user.branch_id, 'special_sidebar_width', '100')
            
            data = {
                'special_width_pct': int(special_width_pct) if str(special_width_pct).isdigit() else 100,
                'special_height_px': int(special_height_px) if str(special_height_px).isdigit() else 40,
                'special_font_px': int(special_font_px) if str(special_font_px).isdigit() else 11,
                'special_spacing_px': int(special_spacing_px) if str(special_spacing_px).isdigit() else 8,
                'special_sidebar_width': int(special_sidebar_width) if str(special_sidebar_width).isdigit() else 100,
            }
            return jsonify({'success': True, 'data': data})
        except Exception as e2:
            return jsonify({'success': False, 'error': str(e2)}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@pos.route('/save_special_ui_prefs', methods=['POST'])
@login_required
def save_special_ui_prefs():
    """Save special items UI preferences for current user and branch"""
    if current_user.role.name not in ['CASHIER', 'WAITER']:
        return jsonify({'success': False, 'error': 'Only cashiers and waiters can save preferences'}), 403
    try:
        payload = request.get_json() or {}
        
        # Get parameters with validation
        special_width_pct = int(payload.get('special_width_pct', 100))
        special_height_px = int(payload.get('special_height_px', 40))
        special_font_px = int(payload.get('special_font_px', 11))
        special_spacing_px = int(payload.get('special_spacing_px', 8))
        special_sidebar_width = int(payload.get('special_sidebar_width', 100))
        
        # Validate ranges
        special_width_pct = max(40, min(100, special_width_pct))  # Changed minimum to 40%
        special_height_px = max(40, min(120, special_height_px))
        special_font_px = max(8, min(20, special_font_px))
        special_spacing_px = max(4, min(16, special_spacing_px))
        special_sidebar_width = max(60, min(100, special_sidebar_width))  # Sidebar width 60-100%
        
        # Save settings
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_width_pct', str(special_width_pct))
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_height_px', str(special_height_px))
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_font_px', str(special_font_px))
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_spacing_px', str(special_spacing_px))
        CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_sidebar_width', str(special_sidebar_width))
        
        db.session.commit()
        
        # Log the customization change
        AuditLog.log_action(
            user_id=current_user.id,
            action='CUSTOMIZE_SPECIAL_ITEMS',
            details=f'Updated special items preferences: width={special_width_pct}%, height={special_height_px}px, font={special_font_px}px, spacing={special_spacing_px}px',
            branch_id=current_user.branch_id
        )
        
        # Return updated values
        result = {
            'special_width_pct': special_width_pct,
            'special_height_px': special_height_px,
            'special_font_px': special_font_px,
            'special_spacing_px': special_spacing_px,
            'special_sidebar_width': special_sidebar_width,
        }
        return jsonify({'success': True, 'data': result})
    except (OperationalError, ProgrammingError):
        # Create tables and retry once
        db.create_all()
        try:
            payload = request.get_json() or {}
            
            special_width_pct = int(payload.get('special_width_pct', 100))
            special_height_px = int(payload.get('special_height_px', 40))
            special_font_px = int(payload.get('special_font_px', 11))
            special_spacing_px = int(payload.get('special_spacing_px', 8))
            special_sidebar_width = int(payload.get('special_sidebar_width', 100))
            
            special_width_pct = max(40, min(100, special_width_pct))
            special_height_px = max(40, min(120, special_height_px))
            special_font_px = max(8, min(20, special_font_px))
            special_spacing_px = max(4, min(16, special_spacing_px))
            special_sidebar_width = max(60, min(100, special_sidebar_width))
            
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_width_pct', str(special_width_pct))
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_height_px', str(special_height_px))
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_font_px', str(special_font_px))
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_spacing_px', str(special_spacing_px))
            CashierUiSetting.set_value(current_user.id, current_user.branch_id, 'special_sidebar_width', str(special_sidebar_width))
            
            db.session.commit()
            
            AuditLog.log_action(
                user_id=current_user.id,
                action='CUSTOMIZE_SPECIAL_ITEMS',
                details=f'Updated special items preferences: width={special_width_pct}%, height={special_height_px}px, font={special_font_px}px, spacing={special_spacing_px}px',
                branch_id=current_user.branch_id
            )
            
            result = {
                'special_width_pct': special_width_pct,
                'special_height_px': special_height_px,
                'special_font_px': special_font_px,
                'special_spacing_px': special_spacing_px,
                'special_sidebar_width': special_sidebar_width,
            }
            return jsonify({'success': True, 'data': result})
        except Exception as e2:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e2)}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@pos.route('/get_cashiers_for_assignment')
@login_required
def get_cashiers_for_assignment():
    """Get all cashiers in branch for waiter to select from"""
    try:
        # Only allow waiters to use this endpoint
        if current_user.role != UserRole.WAITER:
            return jsonify({
                'success': False,
                'message': 'Access denied. This feature is only for waiters.'
            })
        
        # Get all cashiers in the branch
        cashiers = User.query.filter_by(
            branch_id=current_user.branch_id,
            role=UserRole.CASHIER,
            is_active=True
        ).order_by(User.first_name, User.last_name).all()
        
        cashiers_data = [{
            'id': cashier.id,
            'name': cashier.get_full_name(),
            'username': cashier.username
        } for cashier in cashiers]
        
        return jsonify({
            'success': True,
            'cashiers': cashiers_data
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error getting cashiers: {str(e)}'
        })

@pos.route('/assign_cashier_to_waiter', methods=['POST'])
@login_required
def assign_cashier_to_waiter():
    """Assign cashier to waiter after cashier PIN verification"""
    try:
        # Only allow waiters to use this endpoint
        if current_user.role != UserRole.WAITER:
            return jsonify({
                'success': False,
                'message': 'Access denied. This feature is only for waiters.'
            })
        
        data = request.get_json()
        cashier_id = data.get('cashier_id')
        cashier_pin = data.get('cashier_pin', '').strip()
        
        if not cashier_id:
            return jsonify({
                'success': False,
                'message': 'Please select a cashier'
            })
        
        if not cashier_pin or len(cashier_pin) != 4 or not cashier_pin.isdigit():
            return jsonify({
                'success': False,
                'message': 'Invalid cashier PIN'
            })
        
        # Verify cashier exists and is in the same branch
        cashier = User.query.filter_by(
            id=cashier_id,
            branch_id=current_user.branch_id,
            role=UserRole.CASHIER,
            is_active=True
        ).first()
        
        if not cashier:
            return jsonify({
                'success': False,
                'message': 'Invalid cashier selected'
            })
        
        # Verify cashier PIN
        is_valid = CashierPin.verify_cashier_pin(
            cashier_id=cashier_id,
            branch_id=current_user.branch_id,
            pin_code=cashier_pin
        )
        
        if not is_valid:
            return jsonify({
                'success': False,
                'message': 'Invalid cashier PIN code'
            })
        
        # Set the assignment (cashier is assigning themselves to the waiter)
        WaiterCashierAssignment.set_assignment(
            waiter_id=current_user.id,
            branch_id=current_user.branch_id,
            cashier_id=cashier_id,
            assigned_by_cashier_id=cashier_id
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'cashier': {
                'id': cashier.id,
                'name': cashier.get_full_name(),
                'username': cashier.username
            },
            'message': f'Orders will now be assigned to {cashier.get_full_name()}'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error assigning cashier: {str(e)}'
        })

@pos.route('/get_assigned_cashier')
@login_required
def get_assigned_cashier():
    """Get currently assigned cashier for waiter from database"""
    try:
        # Only allow waiters to use this endpoint
        if current_user.role != UserRole.WAITER:
            return jsonify({
                'success': False,
                'message': 'Access denied'
            })
        
        # Get assignment from database
        assignment = WaiterCashierAssignment.get_assignment_for_waiter(
            current_user.id, current_user.branch_id
        )
        
        if assignment and assignment.assigned_cashier:
            return jsonify({
                'success': True,
                'cashier': {
                    'id': assignment.assigned_cashier.id,
                    'name': assignment.assigned_cashier.get_full_name(),
                    'username': assignment.assigned_cashier.username
                }
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No cashier assigned. Please enter admin PIN.'
            })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error getting assigned cashier: {str(e)}'
        })

@pos.route('/clear_assigned_cashier', methods=['POST'])
@login_required
def clear_assigned_cashier():
    """Clear assigned cashier from database (for admin override)"""
    try:
        # Only allow waiters to use this endpoint
        if current_user.role != UserRole.WAITER:
            return jsonify({
                'success': False,
                'message': 'Access denied'
            })
        
        # Clear assignment from database
        cleared = WaiterCashierAssignment.clear_assignment(
            current_user.id, current_user.branch_id
        )
        
        if cleared:
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'Cashier assignment cleared'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No assignment found to clear'
            })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Error clearing assignment: {str(e)}'
        })

@pos.route('/verify_admin_pin_for_editing', methods=['POST'])
@login_required
def verify_admin_pin_for_editing():
    """Verify admin PIN specifically for order editing (cashiers only)"""
    if current_user.role != UserRole.CASHIER:
        return jsonify({'success': False, 'message': 'Access denied. This feature is only for cashiers.'})
    
    try:
        data = request.get_json()
        pin_code = data.get('pin_code', '').strip()
        
        if not pin_code or len(pin_code) != 4:
            return jsonify({'success': False, 'message': 'Please enter a 4-digit PIN code'})
        
        # Check for admin PIN specifically for order editing
        from app.models import AdminPinCode
        admin_pin = AdminPinCode.query.filter_by(
            branch_id=current_user.branch_id,
            pin_type='order_editing',  # New PIN type for order editing
            is_active=True
        ).first()
        
        if not admin_pin:
            return jsonify({
                'success': False, 
                'message': 'No admin PIN configured for order editing. Please contact your administrator.'
            })
        
        # Verify the PIN
        if admin_pin.check_pin(pin_code):
            return jsonify({
                'success': True,
                'message': 'PIN verified successfully! You can now edit orders.',
                'admin_name': admin_pin.admin_name or 'Administrator'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid PIN code. Please try again.'
            })
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@pos.route('/manual_card_payment', methods=['POST'])
@login_required
def manual_card_payment():
    """Handle manual card payment entry by cashiers"""
    if current_user.role != UserRole.CASHIER:
        return jsonify({'success': False, 'error': 'Access denied. Only cashiers can enter manual card payments.'})
    
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        notes = data.get('notes', '').strip()
        
        if amount <= 0:
            return jsonify({'success': False, 'error': 'Amount must be greater than 0'})
        
        # Add or update manual card payment
        payment = ManualCardPayment.add_or_update_payment(
            cashier_id=current_user.id,
            branch_id=current_user.branch_id,
            amount=amount,
            notes=notes
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Manual card payment of {amount:.2f} QAR saved successfully',
            'payment_id': payment.id,
            'amount': float(payment.amount)
        })
        
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount format'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

def generate_order_number():
    """Generate a unique order number using configured timezone"""
    # Use configured timezone for order number generation
    local_time = TimezoneManager.get_current_time()
    date_str = local_time.strftime('%Y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"ORD{date_str}{random_str}"
