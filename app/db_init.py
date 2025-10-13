"""Unified Database Initialization for Restaurant POS Multi-Branch System
This module handles creating database tables and initial data with comprehensive duplicate prevention.
"""

import os
import tempfile
import time
from datetime import datetime
from app import db
from app.models import (
    User, Branch, Category, MenuItem, Table, Customer, DeliveryCompany,
    UserRole, PaymentMethod, ServiceType, AuditLog
)
from werkzeug.security import generate_password_hash
import logging

def init_multibranch_db(app):
    """Unified multi-branch database initialization with duplicate prevention"""
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            app.logger.info("Database tables created successfully")
            
            # Fix menu_items schema if needed (PostgreSQL column size issue)
            try:
                from sqlalchemy import text
                app.logger.info("[CONFIG] Checking menu_items schema for PostgreSQL compatibility...")
                
                # Check all problematic columns
                result = db.session.execute(text("""
                    SELECT column_name, character_maximum_length 
                    FROM information_schema.columns 
                    WHERE table_name = 'menu_items' 
                    AND column_name IN ('card_color', 'size_flag', 'portion_type', 'visual_priority')
                    ORDER BY column_name;
                """)).fetchall()
                
                app.logger.info(f"Current column sizes: {[(r[0], r[1]) for r in result]}")
                
                # Check if any column needs fixing
                needs_fix = any(r[1] and r[1] < 10 for r in result if r[1] is not None)
                
                if needs_fix or not result:
                    app.logger.info("[CONFIG] Fixing menu_items column sizes for PostgreSQL compatibility...")
                    migrations = [
                        "ALTER TABLE menu_items ALTER COLUMN card_color TYPE VARCHAR(20);",
                        "ALTER TABLE menu_items ALTER COLUMN size_flag TYPE VARCHAR(10);", 
                        "ALTER TABLE menu_items ALTER COLUMN portion_type TYPE VARCHAR(20);",
                        "ALTER TABLE menu_items ALTER COLUMN visual_priority TYPE VARCHAR(10);"
                    ]
                    
                    for migration in migrations:
                        try:
                            db.session.execute(text(migration))
                            app.logger.info(f"[OK] Applied: {migration}")
                        except Exception as e:
                            app.logger.warning(f"[WARNING] Migration warning: {migration} - {str(e)}")
                    
                    db.session.commit()
                    app.logger.info("[OK] Menu items schema fixed successfully")
                    
                    # Verify the fix
                    result_after = db.session.execute(text("""
                        SELECT column_name, character_maximum_length 
                        FROM information_schema.columns 
                        WHERE table_name = 'menu_items' 
                        AND column_name IN ('card_color', 'size_flag', 'portion_type', 'visual_priority')
                        ORDER BY column_name;
                    """)).fetchall()
                    app.logger.info(f"Updated column sizes: {[(r[0], r[1]) for r in result_after]}")
                else:
                    app.logger.info("[OK] Menu items schema is already correct")
                    
            except Exception as e:
                app.logger.error(f"[ERROR] Schema fix failed: {str(e)}")
                db.session.rollback()
                # Don't continue if schema fix fails - this is critical
                raise e
            
            # Check if data already exists - comprehensive check to prevent duplicates
            existing_branches = Branch.query.count()
            existing_users = User.query.count()
            
            if existing_branches > 0 and existing_users > 0:
                app.logger.info(f"Database already initialized (branches: {existing_branches}, users: {existing_users}), skipping initialization")
                return
            
            app.logger.info(f"Partial initialization detected (branches: {existing_branches}, users: {existing_users}), continuing with missing data...")
            
            app.logger.info("Starting multi-branch database initialization...")
            
            # Create or get default branches
            if existing_branches == 0:
                branches = create_default_branches()
                app.logger.info(f"Created {len(branches)} new branches")
                # Commit branches first to get their IDs
                db.session.commit()
            else:
                branches = Branch.query.all()
                app.logger.info(f"Using {len(branches)} existing branches")
            
            # Create users if they don't exist
            if existing_users == 0:
                # Create super user
                super_user = create_super_user(branches[0].id)
                app.logger.info("Created super user")
                
                # Create sample users for demonstration
                create_sample_users(branches)
                app.logger.info("Created sample users")
            else:
                app.logger.info("Users already exist, skipping user creation")
            
            # Create default data for each branch (if needed)
            for branch in branches:
                # Check if branch already has data
                existing_categories = Category.query.filter_by(branch_id=branch.id).count()
                if existing_categories == 0:
                    create_branch_default_data(branch.id)
                    app.logger.info(f"Created default data for branch: {branch.name}")
                else:
                    app.logger.info(f"Branch {branch.name} already has data, skipping")
            
            # Final commit
            db.session.commit()
            app.logger.info("Multi-branch database initialization completed successfully")
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Database initialization failed: {str(e)}")
            raise e

def create_default_branches():
    """Create default branches with duplicate prevention"""
    branches_data = [
        {
            'name': 'Main Branch',
            'code': 'MAIN',
            'address': 'Main Restaurant Location, Doha, Qatar',
            'phone': '+974-4000-0001',
            'email': 'main@restaurant.com',
            'manager_name': 'Main Branch Manager'
        },
        {
            'name': 'Branch 2 - City Center',
            'code': 'CC01',
            'address': 'City Center Mall, Doha, Qatar',
            'phone': '+974-4000-0002',
            'email': 'citycenter@restaurant.com',
            'manager_name': 'City Center Manager'
        },
        {
            'name': 'Branch 3 - Villaggio',
            'code': 'VIL1',
            'address': 'Villaggio Mall, Doha, Qatar',
            'phone': '+974-4000-0003',
            'email': 'villaggio@restaurant.com',
            'manager_name': 'Villaggio Manager'
        },
        {
            'name': 'Branch 4 - The Pearl',
            'code': 'PRL1',
            'address': 'The Pearl Qatar, Doha, Qatar',
            'phone': '+974-4000-0004',
            'email': 'pearl@restaurant.com',
            'manager_name': 'Pearl Manager'
        },
        {
            'name': 'Branch 5 - West Bay',
            'code': 'WB01',
            'address': 'West Bay Area, Doha, Qatar',
            'phone': '+974-4000-0005',
            'email': 'westbay@restaurant.com',
            'manager_name': 'West Bay Manager'
        }
    ]
    
    branches = []
    for branch_data in branches_data:
        # Check if branch already exists
        existing_branch = Branch.query.filter_by(code=branch_data['code']).first()
        if existing_branch:
            print(f"Branch {branch_data['code']} already exists, skipping...")
            branches.append(existing_branch)
            continue
            
        branch = Branch(
            name=branch_data['name'],
            code=branch_data['code'],
            address=branch_data['address'],
            phone=branch_data['phone'],
            email=branch_data['email'],
            manager_name=branch_data['manager_name'],
            timezone='Asia/Qatar',
            currency='QAR',
            tax_rate=0.0000,  # No tax in Qatar for restaurants
            service_charge=0.1000  # 10% service charge
        )
        db.session.add(branch)
        branches.append(branch)
    
    db.session.flush()  # Get IDs without committing
    return branches

def create_super_user(default_branch_id):
    """Create super user account with duplicate prevention"""
    # Check if super user already exists
    existing_super_user = User.query.filter_by(username='superadmin').first()
    if existing_super_user:
        print("Super user already exists, skipping...")
        return existing_super_user
    
    super_user = User(
        username='superadmin',
        email='superadmin@restaurant.com',
        first_name='Super',
        last_name='Administrator',
        role=UserRole.SUPER_USER,
        branch_id=default_branch_id,
        can_access_multiple_branches=True,
        is_active=True
    )
    super_user.set_password('SuperAdmin123!')
    db.session.add(super_user)
    db.session.flush()
    return super_user

def create_branch_default_data(branch_id):
    """Create default data for a specific branch with duplicate prevention"""
    
    # Check if data already exists for this branch
    existing_categories = Category.query.filter_by(branch_id=branch_id).first()
    if existing_categories:
        print(f"Branch {branch_id} already has data, skipping...")
        return
    
    # Create categories
    categories_data = [
        {'name': 'Quick', 'order_index': 0},
        {'name': 'Homos', 'order_index': 1},
        {'name': 'Foul', 'order_index': 2},
        {'name': 'FATA', 'order_index': 3},
        {'name': 'MIX', 'order_index': 4},
        {'name': 'Falafel', 'order_index': 5},
        {'name': 'Bakery', 'order_index': 6},
        {'name': 'طلبات خاصة', 'order_index': 7}
    ]
    
    categories = {}
    for cat_data in categories_data:
        # Check if category already exists for this branch
        existing_cat = Category.query.filter_by(
            name=cat_data['name'], 
            branch_id=branch_id
        ).first()
        
        if not existing_cat:
            category = Category(
                name=cat_data['name'],
                order_index=cat_data['order_index'],
                branch_id=branch_id,
                is_active=True
            )
            db.session.add(category)
            categories[cat_data['name']] = category
        else:
            categories[cat_data['name']] = existing_cat
    
    db.session.flush()  # Get category IDs
    
    # Create menu items for each category
    create_menu_items(categories, branch_id)
    
    # Create tables
    create_tables(branch_id)
    
    # Create default customer
    create_default_customer(branch_id)
    
    # Create delivery companies
    create_delivery_companies(branch_id)

def create_menu_items(categories, branch_id):
    """Create menu items for all categories with duplicate prevention"""
    
    # Define all menu items by category
    menu_items_by_category = {
        'Homos': [
            {'name': 'Hommos', 'price': 12.00},
            {'name': 'Hommos big', 'price': 18.00},
            {'name': 'mutabbal', 'price': 15.00},
            {'name': 'Hommos and meat', 'price': 22.00},
            {'name': 'musabaha', 'price': 14.00},
            {'name': 'musabaha big', 'price': 20.00},
            {'name': 'special order', 'price': 25.00}
        ],
        'Foul': [
            {'name': 'foul', 'price': 10.00},
            {'name': 'foul big', 'price': 15.00}
        ],
        'FATA': [
            {'name': 'Fata laban', 'price': 16.00},
            {'name': 'Fata tahina', 'price': 18.00}
        ],
        'MIX': [
            {'name': 'MIX', 'price': 20.00},
            {'name': 'MIX BIG', 'price': 28.00}
        ],
        'Falafel': [
            {'name': 'Falafel Hab', 'price': 8.00},
            {'name': 'Falafel Sandwich', 'price': 12.00},
            {'name': 'Falafel Meduim', 'price': 15.00},
            {'name': 'Falafel BIG', 'price': 22.00},
            {'name': 'Vegtable Meduim', 'price': 18.00}
        ],
        'Bakery': [
            {'name': 'Zaatar', 'price': 6.00},
            {'name': 'Spinach Pie', 'price': 8.00},
            {'name': 'Meat', 'price': 12.00},
            {'name': 'Halloum', 'price': 10.00},
            {'name': 'Kashkawan', 'price': 9.00},
            {'name': 'Mashmoula', 'price': 11.00},
            {'name': 'Chease - zaatar', 'price': 8.00},
            {'name': 'labneh-zaatar', 'price': 7.00}
        ],
        'طلبات خاصة': [
            {'name': 'SADA', 'price': 0.00},
            {'name': 'Bedon zeit', 'price': 0.00},
            {'name': 'zeit zyede', 'price': 2.00},
            {'name': 'hab aleel', 'price': 0.00},
            {'name': 'hab zyede', 'price': 3.00},
            {'name': 'ale naem', 'price': 0.00},
            {'name': 'bedon hamod', 'price': 0.00},
            {'name': 'bedon basal', 'price': 0.00},
            {'name': 'extra fil fil', 'price': 1.00},
            {'name': 'extra zeitoun-basal', 'price': 2.00}
        ]
    }
    
    # Create items for each category (except Quick and Special Requests)
    created_items = []
    for category_name, items_data in menu_items_by_category.items():
        if category_name in categories:
            category = categories[category_name]
            
            for item_data in items_data:
                existing_item = MenuItem.query.filter_by(
                    name=item_data['name'],
                    branch_id=branch_id,
                    category_id=category.id
                ).first()
                
                if not existing_item:
                    item = MenuItem(
                        name=item_data['name'],
                        price=item_data['price'],
                        category_id=category.id,
                        branch_id=branch_id,
                        is_active=True,
                        card_color='transparent',
                        size_flag='',
                        portion_type='',
                        visual_priority=''
                    )
                    db.session.add(item)
                    created_items.append(item)
    
    # Flush to get IDs
    db.session.flush()
    
    # Add ALL non-special items to Quick category by default (branch-scoped)
    for cat_name, cat_obj in categories.items():
        if cat_name in ['Quick', 'طلبات خاصة']:
            continue
        # Fetch items in this category for this branch
        items_in_cat = MenuItem.query.filter_by(
            branch_id=branch_id,
            category_id=cat_obj.id
        ).all()
        for item in items_in_cat:
            # Prevent duplicates in Quick for same name and original category
            existing_quick = MenuItem.query.filter_by(
                name=item.name,
                branch_id=branch_id,
                category_id=categories['Quick'].id,
                original_category_id=item.category_id
            ).first()
            if existing_quick:
                continue
            quick_menu_item = MenuItem(
                name=item.name,
                price=item.price,
                category_id=categories['Quick'].id,
                branch_id=branch_id,
                original_category_id=item.category_id,
                is_active=item.is_active,
                image_url=item.image_url,
                description=getattr(item, 'description', None),
                is_vegetarian=item.is_vegetarian,
                is_vegan=item.is_vegan,
                card_color='transparent',
                size_flag='',
                portion_type='',
                visual_priority=''
            )
            db.session.add(quick_menu_item)

def create_tables(branch_id):
    """Create default tables for branch with duplicate prevention"""
    existing_tables = Table.query.filter_by(branch_id=branch_id).first()
    if existing_tables:
        print(f"Tables already exist for branch {branch_id}, skipping...")
        return
        
    for i in range(1, 9):  # Create 8 tables per branch
        table = Table(
            table_number=f"T{i:02d}",
            capacity=4,
            branch_id=branch_id,
            is_active=True
        )
        db.session.add(table)

def create_default_customer(branch_id):
    """Create default walk-in customer with duplicate prevention"""
    existing_customer = Customer.query.filter_by(
        name="Walk-in Customer",
        branch_id=branch_id
    ).first()
    
    if not existing_customer:
        customer = Customer(
            name="Walk-in Customer",
            phone="000-000-0000",
            branch_id=branch_id,
            is_loyalty_member=False
        )
        db.session.add(customer)

def create_delivery_companies(branch_id):
    """Create default delivery companies for branch with duplicate prevention"""
    existing_companies = DeliveryCompany.query.filter_by(branch_id=branch_id).first()
    if existing_companies:
        print(f"Delivery companies already exist for branch {branch_id}, skipping...")
        return
        
    companies = [
        {'name': 'Talabat',  'value': 'talabat',   'icon': 'bi-truck'},
        {'name': 'Delivaroo','value': 'delivaroo', 'icon': 'bi-bicycle'},
        {'name': 'Rafiq',    'value': 'rafiq',     'icon': 'bi-car'},
        {'name': 'Snounou',  'value': 'snounou',   'icon': 'bi-scooter'}
    ]
    
    for company_data in companies:
        company = DeliveryCompany(
            name=company_data['name'],
            value=company_data['value'],
            icon=company_data['icon'],
            branch_id=branch_id,
            is_active=True
        )
        db.session.add(company)

def create_sample_users(branches):
    """Create sample users for demonstration with duplicate prevention"""
    
    # Create branch admins for each branch
    for i, branch in enumerate(branches):
        admin_username = f'admin{i+1}'
        existing_admin = User.query.filter_by(username=admin_username).first()
        
        if not existing_admin:
            admin = User(
                username=admin_username,
                email=f'admin{i+1}@restaurant.com',
                first_name=f'Admin',
                last_name=f'Branch{i+1}',
                role=UserRole.BRANCH_ADMIN,
                branch_id=branch.id,
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
        
        # Create cashiers for each branch
        cashier_count = 2 if i == 0 else 1  # Main branch has 2 cashiers
        for j in range(cashier_count):
            cashier_username = f'cashier{i+1}_{j+1}'
            existing_cashier = User.query.filter_by(username=cashier_username).first()
            
            if not existing_cashier:
                cashier = User(
                    username=cashier_username,
                    email=f'cashier{i+1}_{j+1}@restaurant.com',
                    first_name=f'Cashier{j+1}',
                    last_name=f'Branch{i+1}',
                    role=UserRole.CASHIER,
                    branch_id=branch.id,
                    is_active=True
                )
                cashier.set_password('cashier123')
                db.session.add(cashier)
        
        # Create waiter for each branch
        waiter_username = f'waiter{i+1}'
        existing_waiter = User.query.filter_by(username=waiter_username).first()
        
        if not existing_waiter:
            waiter = User(
                username=waiter_username,
                email=f'waiter{i+1}@restaurant.com',
                first_name=f'Waiter',
                last_name=f'Branch{i+1}',
                role=UserRole.WAITER,
                branch_id=branch.id,
                is_active=True
            )
            waiter.set_password('waiter123')
            db.session.add(waiter)

def create_delivery_companies(branch_id):
    """Create default delivery companies for branch with duplicate prevention"""
    existing_companies = DeliveryCompany.query.filter_by(branch_id=branch_id).first()
    if existing_companies:
        print(f"Delivery companies already exist for branch {branch_id}, skipping...")
        return
        
    # Default delivery companies
    companies_data = [
        {'name': 'Talabat',  'value': 'talabat',   'icon': 'bi-truck'},
        {'name': 'Delivaroo','value': 'delivaroo', 'icon': 'bi-bicycle'},
        {'name': 'Rafiq',    'value': 'rafiq',     'icon': 'bi-car'},
        {'name': 'Snounou',  'value': 'snounou',   'icon': 'bi-scooter'}
    ]
    
    for company_data in companies_data:
        company = DeliveryCompany(
            name=company_data['name'],
            value=company_data['value'],
            icon=company_data['icon'],
            branch_id=branch_id,
            is_active=True
        )
        db.session.add(company)

# Legacy function for backward compatibility
def init_db(app):
    """Legacy function - redirects to multi-branch initialization"""
    return init_multibranch_db(app)

# Lazy initialization for production deployment
def init_db_lazy(app):
    """Lazy database initialization for production deployment"""
    return init_multibranch_db(app)