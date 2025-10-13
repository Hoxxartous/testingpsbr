from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app import db
from sqlalchemy import func
from enum import Enum
from typing import Union
import pytz
from flask import current_app

# Enhanced user roles for multi-branch system
class UserRole(Enum):
    SUPER_USER = 'super_user'      # Can manage all branches and users
    BRANCH_ADMIN = 'branch_admin'  # Can manage specific branch
    MANAGER = 'manager'            # Branch manager
    CASHIER = 'cashier'           # Cashier for specific branch
    WAITER = 'waiter'             # Waiter for specific branch
    KITCHEN = 'kitchen'           # Kitchen staff for specific branch

# Enum for payment methods
class PaymentMethod(Enum):
    CASH = 'cash'
    CARD = 'card'
    QR_CODE = 'qr_code'

# Enum for service types
class ServiceType(Enum):
    ON_TABLE = 'on_table'
    TAKE_AWAY = 'take_away'
    DELIVERY = 'delivery'
    CARD = 'card'

# Enum for order status
class OrderStatus(Enum):
    PENDING = 'pending'    # Order created but not paid (especially for waiter orders)
    PAID = 'paid'         # Order has been paid and counts toward revenue
    CANCELLED = 'cancelled'  # Order was cancelled

# Branch model - Core of multi-branch system
class Branch(db.Model):
    __tablename__ = 'branches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    code = db.Column(db.String(16), unique=True, nullable=False)
    address = db.Column(db.Text)
    phone = db.Column(db.String(32))
    email = db.Column(db.String(128))
    manager_name = db.Column(db.String(128))
    is_active = db.Column(db.Boolean(), default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Branch settings
    timezone = db.Column(db.String(64), default='UTC')
    currency = db.Column(db.String(8), default='QAR')
    tax_rate = db.Column(db.Numeric(5, 4), default=0.0000)
    service_charge = db.Column(db.Numeric(5, 4), default=0.0000)
    
    # Relationships
    users = db.relationship('User', backref='branch', lazy='dynamic')
    categories = db.relationship('Category', backref='branch', lazy='dynamic')
    menu_items = db.relationship('MenuItem', backref='branch', lazy='dynamic')
    tables = db.relationship('Table', backref='branch', lazy='dynamic')
    customers = db.relationship('Customer', backref='branch', lazy='dynamic')
    orders = db.relationship('Order', backref='branch', lazy='dynamic')
    inventory_items = db.relationship('InventoryItem', backref='branch', lazy='dynamic')
    delivery_companies = db.relationship('DeliveryCompany', backref='branch', lazy='dynamic')
    
    def __repr__(self):
        return f'<Branch {self.name} ({self.code})>'

# Enhanced User model with branch support
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    email = db.Column(db.String(120), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    first_name = db.Column(db.String(64), nullable=False)
    last_name = db.Column(db.String(64), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.CASHIER)
    is_active = db.Column(db.Boolean(), default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Multi-branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    can_access_multiple_branches = db.Column(db.Boolean(), default=False)
    
    # Relationships
    audit_logs = db.relationship('AuditLog', backref='user', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
        
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def is_super_user(self):
        return self.role == UserRole.SUPER_USER
    
    def is_branch_admin(self):
        return self.role == UserRole.BRANCH_ADMIN
    
    def can_manage_branch(self, branch_id):
        """Check if user can manage specific branch"""
        if self.is_super_user():
            return True
        if self.is_branch_admin() and self.branch_id == branch_id:
            return True
        return False
    
    def get_accessible_branches(self):
        """Get all branches this user can access"""
        if self.is_super_user():
            return Branch.query.filter_by(is_active=True).all()
        elif self.branch_id:
            return [self.branch]
        return []
        
    def record_login(self):
        """Record user login time"""
        self.last_login = datetime.utcnow()
        db.session.commit()
        
    def __repr__(self):
        return f'<User {self.username}>'

# User-Branch assignment for multi-branch access
class UserBranchAssignment(db.Model):
    __tablename__ = 'user_branch_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    is_active = db.Column(db.Boolean(), default=True)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='branch_assignments')
    branch = db.relationship('Branch', backref='user_assignments')
    assigner = db.relationship('User', foreign_keys=[assigned_by])
    
    def __repr__(self):
        return f'<UserBranchAssignment User:{self.user_id} Branch:{self.branch_id}>'

class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), index=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean(), default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order_index = db.Column(db.Integer, default=0)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    # Relationships
    items = db.relationship('MenuItem', foreign_keys='MenuItem.category_id', backref='category', lazy='dynamic')
    original_items = db.relationship('MenuItem', foreign_keys='MenuItem.original_category_id', backref='original_category', lazy='dynamic')
    
    def __repr__(self):
        return f'<Category {self.name} (Branch: {self.branch_id})>'

class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True, nullable=False)
    name_ar = db.Column(db.String(128), index=True)
    description = db.Column(db.Text)
    description_ar = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    cost = db.Column(db.Numeric(10, 2))
    image_url = db.Column(db.String(256))
    is_active = db.Column(db.Boolean(), default=True, nullable=False)
    is_vegetarian = db.Column(db.Boolean(), default=False)
    is_vegan = db.Column(db.Boolean(), default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Visual customization
    card_color = db.Column(db.String(20), default='transparent')
    size_flag = db.Column(db.String(10), default='')
    portion_type = db.Column(db.String(20), default='')
    visual_priority = db.Column(db.String(10), default='')
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    original_category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='menu_item', lazy='dynamic')
    
    def __repr__(self):
        return f'<MenuItem {self.name} (Branch: {self.branch_id})>'

class Table(db.Model):
    __tablename__ = 'tables'
    
    id = db.Column(db.Integer, primary_key=True)
    table_number = db.Column(db.String(16), index=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean(), default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    # Relationships
    orders = db.relationship('Order', backref='table', lazy='dynamic')
    
    def __repr__(self):
        return f'<Table {self.table_number} (Branch: {self.branch_id})>'

class Customer(db.Model):
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(32), index=True)
    email = db.Column(db.String(128), index=True)
    is_loyalty_member = db.Column(db.Boolean(), default=False)
    total_spent = db.Column(db.Numeric(12, 2), default=0.00)
    visits_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    # Relationships
    orders = db.relationship('Order', backref='customer', lazy='dynamic')
    
    def __repr__(self):
        return f'<Customer {self.name} (Branch: {self.branch_id})>'

class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(32), index=True, nullable=False)
    order_counter = db.Column(db.Integer, nullable=True, index=True)  # Sequential counter per branch
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    discount_amount = db.Column(db.Numeric(10, 2), default=0.00)
    tax_amount = db.Column(db.Numeric(10, 2), default=0.00)
    payment_method = db.Column(db.Enum(PaymentMethod))
    service_type = db.Column(db.Enum(ServiceType), default=ServiceType.ON_TABLE)
    status = db.Column(db.Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    delivery_company_id = db.Column(db.Integer, db.ForeignKey('delivery_companies.id'), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at = db.Column(db.DateTime)  # When the order was marked as paid
    cleared_from_waiter_requests = db.Column(db.Boolean, default=False)  # Hidden from waiter requests page
    
    # Order editing tracking
    last_edited_at = db.Column(db.DateTime)  # When the order was last edited
    last_edited_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Who last edited the order
    edit_count = db.Column(db.Integer, default=0)  # Number of times order has been edited
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    # Foreign keys
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # Who created the order
    assigned_cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # Which cashier waiter assigned order to
    table_id = db.Column(db.Integer, db.ForeignKey('tables.id'))
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    
    # Relationships
    order_items = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    delivery_company_info = db.relationship('DeliveryCompany', backref='orders', lazy='select')
    
    # Cashier relationships
    cashier = db.relationship('User', foreign_keys=[cashier_id], backref='created_orders')
    assigned_cashier = db.relationship('User', foreign_keys=[assigned_cashier_id], backref='assigned_orders')
    
    def __repr__(self):
        return f'<Order {self.order_number} (Branch: {self.branch_id})>'

class OrderEditHistory(db.Model):
    __tablename__ = 'order_edit_history'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    edited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    original_total = db.Column(db.Numeric(10, 2), nullable=False)
    new_total = db.Column(db.Numeric(10, 2), nullable=False)
    changes_summary = db.Column(db.Text)
    
    # Relationships
    order = db.relationship('Order', backref='edit_history')
    editor = db.relationship('User', backref='order_edits')
    
    def __repr__(self):
        return f'<OrderEditHistory Order:{self.order_id} EditedBy:{self.edited_by}>'

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text)
    special_requests = db.Column(db.Text)  # For special requests/modifications
    is_new = db.Column(db.Boolean, default=False)  # Track if item was added during edit
    is_deleted = db.Column(db.Boolean, default=False)  # Track if item was deleted during edit
    
    # Foreign keys
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_items.id'), nullable=False)
    
    def __repr__(self):
        return f'<OrderItem {self.id}>'

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.Enum(PaymentMethod), nullable=False)
    transaction_id = db.Column(db.String(128))
    status = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign key
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    
    def __repr__(self):
        return f'<Payment {self.id}>'

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def __repr__(self):
        return f'<AuditLog {self.action}>'

class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), default=0.00)
    min_quantity = db.Column(db.Numeric(10, 2), default=0.00)
    cost_per_unit = db.Column(db.Numeric(10, 2))
    supplier = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    def __repr__(self):
        return f'<InventoryItem {self.name} (Branch: {self.branch_id})>'

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean(), default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign key
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    def __repr__(self):
        return f'<Notification {self.title}>'

class CashierSession(db.Model):
    __tablename__ = 'cashier_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(128), nullable=False, index=True)
    login_date = db.Column(db.Date, nullable=False, index=True)
    initial_order_count = db.Column(db.Integer, default=0)
    current_order_count = db.Column(db.Integer, default=0)
    daily_report_printed = db.Column(db.Boolean(), default=False)
    report_printed_at = db.Column(db.DateTime)
    session_start = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean(), default=True)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    # Foreign key
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    cashier = db.relationship('User', backref='cashier_sessions')
    
    def __repr__(self):
        return f'<CashierSession {self.session_id} (Branch: {self.branch_id})>'

    @classmethod
    def get_or_create_today_session(cls, cashier_id: int):
        """Get or create an active cashier session for today.
        Ensures a single active session per cashier per day.
        """
        today = datetime.utcnow().date()
        session = cls.query.filter(
            cls.cashier_id == cashier_id,
            cls.login_date == today,
            cls.is_active == True
        ).first()
        if session:
            return session

        # Determine initial order count for today
        initial_count = db.session.query(func.count(Order.id)).filter(
            Order.cashier_id == cashier_id,
            func.date(Order.created_at) == today
        ).scalar() or 0

        # Create a minimal session id; detailed id is constructed in views when available
        sid = f"cashier_{cashier_id}_{today}"
        session = cls(
            session_id=sid,
            login_date=today,
            initial_order_count=initial_count,
            current_order_count=initial_count,
            cashier_id=cashier_id,
            # Branch will be set by callers who know the current user branch
            branch_id=getattr(User.query.get(cashier_id), 'branch_id', None) or 0
        )
        db.session.add(session)
        db.session.commit()
        return session

    def update_order_count(self, count: int):
        self.current_order_count = count
        self.last_activity = datetime.utcnow()
        db.session.commit()

    def has_completed_orders(self) -> bool:
        return (self.current_order_count or 0) > (self.initial_order_count or 0)

    def needs_daily_report(self) -> bool:
        return self.has_completed_orders() and not bool(self.daily_report_printed)

    def mark_report_printed(self):
        self.daily_report_printed = True
        self.report_printed_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        db.session.commit()

class OrderCounter(db.Model):
    __tablename__ = 'order_counters'
    
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    current_counter = db.Column(db.Integer, default=0, nullable=False)
    last_reset_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    branch = db.relationship('Branch', backref='order_counter')
    
    # Unique constraint to ensure one counter per branch
    __table_args__ = (db.UniqueConstraint('branch_id', name='unique_counter_per_branch'),)
    
    def __repr__(self):
        return f'<OrderCounter Branch:{self.branch_id} Counter:{self.current_counter}>'
    
    @classmethod
    def get_next_counter(cls, branch_id):
        """Get the next counter number for a branch"""
        counter_record = cls.query.filter_by(branch_id=branch_id).first()
        if not counter_record:
            # Create new counter record for this branch
            counter_record = cls(branch_id=branch_id, current_counter=1)
            db.session.add(counter_record)
            db.session.flush()
            return 1
        else:
            # Increment and return next counter
            counter_record.current_counter += 1
            counter_record.updated_at = datetime.utcnow()
            db.session.flush()
            return counter_record.current_counter
    
    @classmethod
    def reset_counter(cls, branch_id):
        """Reset counter for a specific branch"""
        counter_record = cls.query.filter_by(branch_id=branch_id).first()
        if counter_record:
            counter_record.current_counter = 0
            counter_record.last_reset_date = datetime.utcnow().date()
            counter_record.updated_at = datetime.utcnow()
        else:
            # Create new counter record
            counter_record = cls(
                branch_id=branch_id, 
                current_counter=0,
                last_reset_date=datetime.utcnow().date()
            )
            db.session.add(counter_record)
        db.session.flush()
    
    @classmethod
    def reset_all_counters(cls):
        """Reset counters for all branches"""
        reset_date = datetime.utcnow().date()
        cls.query.update({
            'current_counter': 0,
            'last_reset_date': reset_date,
            'updated_at': datetime.utcnow()
        })
        db.session.flush()

class DeliveryCompany(db.Model):
    __tablename__ = 'delivery_companies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50), default='bi-truck', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Branch support
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    
    def __repr__(self):
        return f'<DeliveryCompany {self.name} (Branch: {self.branch_id})>'
    
    def to_dict(self):
        """Serialize delivery company for API responses.
        Ensures icon includes both 'bi' base class and a 'bi-*' icon class.
        """
        icon_raw = (self.icon or 'bi-truck').strip()
        # Find an existing 'bi-*' class if present
        bi_icon = None
        for part in icon_raw.split():
            if part.startswith('bi-'):
                bi_icon = part
                break
        if not bi_icon:
            # If no 'bi-*' found, normalize the raw value into one
            if icon_raw.startswith('bi-'):
                bi_icon = icon_raw
            else:
                bi_icon = f'bi-{icon_raw}'
        icon_class = f'bi {bi_icon}'
        return {
            'id': self.id,
            'name': self.name,
            'value': self.value,
            'icon': icon_class,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'branch_id': self.branch_id,
        }
    
    @classmethod
    def get_active_companies_for_branch(cls, branch_id):
        """Get all active delivery companies for specific branch"""
        return cls.query.filter_by(branch_id=branch_id, is_active=True).order_by(cls.name).all()


class CashierUiPreference(db.Model):
    __tablename__ = 'cashier_ui_preferences'

    id = db.Column(db.Integer, primary_key=True)
    # Per cashier and branch isolation
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    # Settings
    card_width_pct = db.Column(db.Integer, default=50, nullable=False)  # percentage width for columns (e.g., 50 = 2 per row)
    card_min_height_px = db.Column(db.Integer, default=160, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Unique per cashier-branch
    __table_args__ = (db.UniqueConstraint('cashier_id', 'branch_id', name='unique_ui_pref_per_cashier_branch'),)

    def to_dict(self):
        return {
            'cashier_id': self.cashier_id,
            'branch_id': self.branch_id,
            'card_width_pct': self.card_width_pct,
            'card_min_height_px': self.card_min_height_px,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CashierUiSetting(db.Model):
    __tablename__ = 'cashier_ui_settings'

    id = db.Column(db.Integer, primary_key=True)
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    key = db.Column(db.String(64), nullable=False)
    value = db.Column(db.String(256), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('cashier_id', 'branch_id', 'key', name='unique_ui_kv_per_cashier_branch'),)

    @staticmethod
    def get_value(cashier_id: int, branch_id: int, key: str, default: Union[str, None] = None):
        rec = CashierUiSetting.query.filter_by(cashier_id=cashier_id, branch_id=branch_id, key=key).first()
        return rec.value if rec else default

    @staticmethod
    def set_value(cashier_id: int, branch_id: int, key: str, value: str):
        rec = CashierUiSetting.query.filter_by(cashier_id=cashier_id, branch_id=branch_id, key=key).first()
        if not rec:
            rec = CashierUiSetting(cashier_id=cashier_id, branch_id=branch_id, key=key, value=str(value))
            db.session.add(rec)
        else:
            rec.value = str(value)
        db.session.flush()


# App-wide settings model for timezone and other global configurations
class AppSettings(db.Model):
    __tablename__ = 'app_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<AppSettings {self.key}: {self.value}>'
    
    @staticmethod
    def get_value(key, default=None):
        """Get a setting value by key"""
        setting = AppSettings.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @staticmethod
    def set_value(key, value, description=None):
        """Set a setting value by key"""
        setting = AppSettings.query.filter_by(key=key).first()
        if not setting:
            setting = AppSettings(key=key, value=str(value), description=description)
            db.session.add(setting)
        else:
            setting.value = str(value)
            if description:
                setting.description = description
        db.session.flush()
        return setting


# Timezone utility functions
class TimezoneManager:
    """Utility class for managing timezone operations"""
    
    @staticmethod
    def get_app_timezone():
        """Get the configured application timezone"""
        timezone_str = AppSettings.get_value('app_timezone', 'Asia/Qatar')
        try:
            return pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError:
            # Fallback to Qatar timezone if invalid timezone is configured
            return pytz.timezone('Asia/Qatar')
    
    @staticmethod
    def get_current_time():
        """Get current time in the configured timezone"""
        app_tz = TimezoneManager.get_app_timezone()
        utc_now = datetime.utcnow().replace(tzinfo=pytz.UTC)
        return utc_now.astimezone(app_tz)
    
    @staticmethod
    def convert_utc_to_local(utc_datetime):
        """Convert UTC datetime to local timezone"""
        if not utc_datetime:
            return None
        
        app_tz = TimezoneManager.get_app_timezone()
        
        # If datetime is naive, assume it's UTC
        if utc_datetime.tzinfo is None:
            utc_datetime = utc_datetime.replace(tzinfo=pytz.UTC)
        
        return utc_datetime.astimezone(app_tz)
    
    @staticmethod
    def convert_local_to_utc(local_datetime):
        """Convert local timezone datetime to UTC"""
        if not local_datetime:
            return None
            
        app_tz = TimezoneManager.get_app_timezone()
        
        # If datetime is naive, assume it's in app timezone
        if local_datetime.tzinfo is None:
            local_datetime = app_tz.localize(local_datetime)
        
        return local_datetime.astimezone(pytz.UTC)
    
    @staticmethod
    def format_local_time(utc_datetime, format_str='%Y-%m-%d %H:%M:%S'):
        """Format UTC datetime as local time string"""
        if not utc_datetime:
            return ''
        
        local_time = TimezoneManager.convert_utc_to_local(utc_datetime)
        return local_time.strftime(format_str)
    
    @staticmethod
    def get_available_timezones():
        """Get list of common timezones for selection"""
        return [
            ('Asia/Qatar', 'Qatar (AST +03:00)'),
            ('Asia/Dubai', 'UAE (GST +04:00)'),
            ('Asia/Kuwait', 'Kuwait (AST +03:00)'),
            ('Asia/Bahrain', 'Bahrain (AST +03:00)'),
            ('Asia/Riyadh', 'Saudi Arabia (AST +03:00)'),
            ('Europe/London', 'London (GMT/BST)'),
            ('Europe/Paris', 'Paris (CET/CEST)'),
            ('America/New_York', 'New York (EST/EDT)'),
            ('America/Los_Angeles', 'Los Angeles (PST/PDT)'),
            ('Asia/Tokyo', 'Tokyo (JST +09:00)'),
            ('Asia/Shanghai', 'Shanghai (CST +08:00)'),
            ('Asia/Kolkata', 'India (IST +05:30)'),
            ('UTC', 'UTC (Coordinated Universal Time)')
        ]


class AdminPinCode(db.Model):
    __tablename__ = 'admin_pin_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Made nullable for new PIN types
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    pin_code_hash = db.Column(db.String(128), nullable=False)  # Hashed PIN for security
    pin_type = db.Column(db.String(50), nullable=False, default='waiter_assignment')  # 'waiter_assignment' or 'order_editing'
    admin_name = db.Column(db.String(100), nullable=True)  # Name of admin for display
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Legacy field for backward compatibility
    pin_code = db.Column(db.String(4), nullable=True)  # Keep for existing data
    
    # Relationships
    admin = db.relationship('User', foreign_keys=[admin_id], backref='admin_pin_codes')
    branch = db.relationship('Branch', backref='admin_pin_codes')
    
    # Constraint for order editing PINs only (one per branch)
    __table_args__ = (db.UniqueConstraint('branch_id', 'pin_type', name='unique_pin_per_type_per_branch'),)
    
    def __repr__(self):
        return f'<AdminPinCode Admin:{self.admin_id} Branch:{self.branch_id}>'
    
    @classmethod
    def get_pin_for_admin(cls, admin_id, branch_id):
        """Get PIN code for specific admin in specific branch"""
        return cls.query.filter_by(admin_id=admin_id, branch_id=branch_id).first()
    
    def set_pin(self, pin_code):
        """Set PIN code with hashing"""
        from werkzeug.security import generate_password_hash
        self.pin_code_hash = generate_password_hash(pin_code)
        self.pin_code = pin_code  # Keep for legacy compatibility
    
    def check_pin(self, pin_code):
        """Check PIN code against hash"""
        from werkzeug.security import check_password_hash
        # Try new hashed PIN first
        if self.pin_code_hash:
            return check_password_hash(self.pin_code_hash, pin_code)
        # Fall back to legacy plain text PIN
        elif self.pin_code:
            return self.pin_code == pin_code
        return False
    
    @classmethod
    def get_pin_for_admin(cls, admin_id, branch_id):
        """Get PIN code for specific admin in specific branch (legacy method)"""
        return cls.query.filter_by(admin_id=admin_id, branch_id=branch_id, is_active=True).first()
    
    @classmethod
    def verify_pin(cls, branch_id, pin_code):
        """Verify PIN code for the branch (legacy method)"""
        pin_record = cls.query.filter_by(branch_id=branch_id, is_active=True).first()
        if pin_record:
            return pin_record.check_pin(pin_code)
        return False


class CashierPin(db.Model):
    __tablename__ = 'cashier_pins'
    
    id = db.Column(db.Integer, primary_key=True)
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    pin_code_hash = db.Column(db.String(128), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    cashier = db.relationship('User', foreign_keys=[cashier_id], backref='cashier_pins')
    branch = db.relationship('Branch', backref='cashier_pins')
    
    # Unique constraint - one PIN per cashier per branch
    __table_args__ = (db.UniqueConstraint('cashier_id', 'branch_id', name='unique_cashier_pin_per_branch'),)
    
    def set_pin(self, pin_code):
        """Set PIN code with hashing"""
        from werkzeug.security import generate_password_hash
        self.pin_code_hash = generate_password_hash(pin_code)
    
    def check_pin(self, pin_code):
        """Check PIN code against hash"""
        from werkzeug.security import check_password_hash
        return check_password_hash(self.pin_code_hash, pin_code)
    
    @classmethod
    def verify_cashier_pin(cls, cashier_id, branch_id, pin_code):
        """Verify PIN code for a specific cashier"""
        pin_record = cls.query.filter_by(
            cashier_id=cashier_id,
            branch_id=branch_id,
            is_active=True
        ).first()
        
        if pin_record:
            return pin_record.check_pin(pin_code)
        return False
    
    def __repr__(self):
        return f'<CashierPin Cashier:{self.cashier_id} Branch:{self.branch_id}>'


class WaiterCashierAssignment(db.Model):
    __tablename__ = 'waiter_cashier_assignments'
    
    id = db.Column(db.Integer, primary_key=True)
    waiter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    assigned_cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assigned_by_cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    waiter = db.relationship('User', foreign_keys=[waiter_id], backref='cashier_assignments')
    branch = db.relationship('Branch', backref='waiter_cashier_assignments')
    assigned_cashier = db.relationship('User', foreign_keys=[assigned_cashier_id], backref='assigned_waiters')
    assigned_by_cashier = db.relationship('User', foreign_keys=[assigned_by_cashier_id], backref='cashier_assignments_made')
    
    # Unique constraint to ensure one assignment per waiter per branch
    __table_args__ = (db.UniqueConstraint('waiter_id', 'branch_id', name='unique_waiter_assignment_per_branch'),)
    
    def __repr__(self):
        return f'<WaiterCashierAssignment Waiter:{self.waiter_id} -> Cashier:{self.assigned_cashier_id}>'
    
    @classmethod
    def get_assignment_for_waiter(cls, waiter_id, branch_id):
        """Get current cashier assignment for waiter"""
        return cls.query.filter_by(waiter_id=waiter_id, branch_id=branch_id).first()
    
    @classmethod
    def set_assignment(cls, waiter_id, branch_id, cashier_id, assigned_by_cashier_id=None):
        """Set or update cashier assignment for waiter"""
        assignment = cls.query.filter_by(waiter_id=waiter_id, branch_id=branch_id).first()
        if assignment:
            assignment.assigned_cashier_id = cashier_id
            assignment.assigned_by_cashier_id = assigned_by_cashier_id
            assignment.updated_at = datetime.utcnow()
        else:
            assignment = cls(
                waiter_id=waiter_id,
                branch_id=branch_id,
                assigned_cashier_id=cashier_id,
                assigned_by_cashier_id=assigned_by_cashier_id
            )
            db.session.add(assignment)
        db.session.flush()
        return assignment
    
    @classmethod
    def clear_assignment(cls, waiter_id, branch_id):
        """Clear cashier assignment for waiter"""
        assignment = cls.query.filter_by(waiter_id=waiter_id, branch_id=branch_id).first()
        if assignment:
            db.session.delete(assignment)
            db.session.flush()
            return True
        return False

# Manual Card Payment model for cashier-entered card payments
class ManualCardPayment(db.Model):
    __tablename__ = 'manual_card_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Branch and cashier information
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Optional notes
    notes = db.Column(db.Text)
    
    # Relationships
    branch = db.relationship('Branch', backref='manual_card_payments')
    cashier = db.relationship('User', backref='manual_card_payments')
    
    def __repr__(self):
        return f'<ManualCardPayment {self.amount} QAR on {self.date} by {self.cashier.get_full_name()}>'
    
    @classmethod
    def get_total_for_date_and_branch(cls, date, branch_id):
        """Get total manual card payments for a specific date and branch"""
        total = db.session.query(func.sum(cls.amount)).filter(
            cls.date == date,
            cls.branch_id == branch_id
        ).scalar()
        return total or 0
    
    @classmethod
    def get_total_for_date_range_and_branch(cls, start_date, end_date, branch_id):
        """Get total manual card payments for a date range and branch"""
        total = db.session.query(func.sum(cls.amount)).filter(
            cls.date >= start_date,
            cls.date <= end_date,
            cls.branch_id == branch_id
        ).scalar()
        return total or 0
    
    @classmethod
    def get_cashier_entry_for_date(cls, cashier_id, date):
        """Check if cashier has already entered card payment for today"""
        return cls.query.filter_by(
            cashier_id=cashier_id,
            date=date
        ).first()
    
    @classmethod
    def add_or_update_payment(cls, cashier_id, branch_id, amount, date=None, notes=None):
        """Add or update manual card payment for cashier"""
        if date is None:
            date = datetime.utcnow().date()
        
        # Check if entry already exists for this cashier and date
        existing = cls.get_cashier_entry_for_date(cashier_id, date)
        
        if existing:
            # Update existing entry
            existing.amount = amount
            existing.notes = notes
            existing.created_at = datetime.utcnow()
            return existing
        else:
            # Create new entry
            payment = cls(
                amount=amount,
                date=date,
                branch_id=branch_id,
                cashier_id=cashier_id,
                notes=notes
            )
            db.session.add(payment)
            return payment
