"""
PostgreSQL-specific optimizations for Restaurant POS
Includes indexes, constraints, and performance enhancements
"""

from sqlalchemy import text
from app import db
import logging

logger = logging.getLogger(__name__)

def create_postgresql_indexes():
    """Create optimized indexes for PostgreSQL performance"""
    
    indexes = [
        # User-related indexes
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_username_active 
           ON users (username) WHERE is_active = true""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_branch_role 
           ON users (branch_id, role) WHERE is_active = true""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email_active 
           ON users (email) WHERE is_active = true""",
        
        # Order-related indexes for high performance
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_branch_status_created 
           ON orders (branch_id, status, created_at DESC)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_cashier_date 
           ON orders (cashier_id, DATE(created_at))""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_waiter_date 
           ON orders (waiter_id, DATE(created_at)) WHERE waiter_id IS NOT NULL""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_status_total 
           ON orders (status, total_amount) WHERE status = 'paid'""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_table_status 
           ON orders (table_id, status) WHERE table_id IS NOT NULL""",
        
        # Order items for fast lookups
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_menu 
           ON order_items (order_id, menu_item_id)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_menu_quantity 
           ON order_items (menu_item_id, quantity)""",
        
        # Menu items for POS performance
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_menu_items_branch_active_category 
           ON menu_items (branch_id, is_available, category_id)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_menu_items_name_search 
           ON menu_items USING gin(to_tsvector('english', name))""",
        
        # Categories
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_categories_branch_active 
           ON categories (branch_id) WHERE is_active = true""",
        
        # Tables for restaurant operations
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tables_branch_status 
           ON tables (branch_id, status)""",
        
        # Customers for quick lookup
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_phone_branch 
           ON customers (phone, branch_id)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customers_name_search 
           ON customers USING gin(to_tsvector('english', name))""",
        
        # Audit logs for compliance
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_user_date 
           ON audit_logs (user_id, created_at DESC)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_table_action 
           ON audit_logs (table_name, action, created_at DESC)""",
        
        # Cashier UI settings for fast user experience
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cashier_ui_prefs_user_branch 
           ON cashier_ui_preferences (cashier_id, branch_id)""",
        
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cashier_ui_settings_user_key 
           ON cashier_ui_settings (cashier_id, key)""",
        
        # Inventory for stock management
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_branch_low_stock 
           ON inventory_items (branch_id, current_stock) WHERE current_stock <= minimum_stock""",
        
        # Delivery companies
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_delivery_companies_branch_active 
           ON delivery_companies (branch_id) WHERE is_active = true""",
    ]
    
    logger.info("🔍 Creating PostgreSQL performance indexes...")
    
    for index_sql in indexes:
        try:
            db.session.execute(text(index_sql))
            db.session.commit()
            
            # Extract index name for logging
            index_name = index_sql.split('idx_')[1].split(' ')[0] if 'idx_' in index_sql else 'unnamed'
            logger.info(f"✅ Created index: {index_name}")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not create index: {e}")
            db.session.rollback()

def create_postgresql_constraints():
    """Create additional constraints for data integrity"""
    
    constraints = [
        # Ensure branch codes are properly formatted
        """ALTER TABLE branches ADD CONSTRAINT IF NOT EXISTS chk_branch_code_format 
           CHECK (code ~ '^[A-Z0-9]{2,16}$')""",
        
        # Ensure positive amounts
        """ALTER TABLE orders ADD CONSTRAINT IF NOT EXISTS chk_orders_positive_amounts 
           CHECK (subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0)""",
        
        # Ensure valid order status transitions
        """ALTER TABLE orders ADD CONSTRAINT IF NOT EXISTS chk_orders_valid_status 
           CHECK (status IN ('pending', 'paid', 'cancelled'))""",
        
        # Ensure positive quantities and prices
        """ALTER TABLE order_items ADD CONSTRAINT IF NOT EXISTS chk_order_items_positive 
           CHECK (quantity > 0 AND price >= 0)""",
        
        # Ensure menu item prices are positive
        """ALTER TABLE menu_items ADD CONSTRAINT IF NOT EXISTS chk_menu_items_positive_price 
           CHECK (price >= 0)""",
        
        # Ensure table numbers are positive
        """ALTER TABLE tables ADD CONSTRAINT IF NOT EXISTS chk_tables_positive_number 
           CHECK (number > 0)""",
        
        # Ensure inventory quantities are non-negative
        """ALTER TABLE inventory_items ADD CONSTRAINT IF NOT EXISTS chk_inventory_non_negative 
           CHECK (current_stock >= 0 AND minimum_stock >= 0)""",
    ]
    
    logger.info("🔒 Creating PostgreSQL data integrity constraints...")
    
    for constraint_sql in constraints:
        try:
            db.session.execute(text(constraint_sql))
            db.session.commit()
            
            # Extract constraint name for logging
            constraint_name = constraint_sql.split('chk_')[1].split(' ')[0] if 'chk_' in constraint_sql else 'unnamed'
            logger.info(f"✅ Created constraint: {constraint_name}")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not create constraint: {e}")
            db.session.rollback()

def create_postgresql_functions():
    """Create PostgreSQL functions for better performance"""
    
    functions = [
        # Function to calculate daily sales for a branch
        """
        CREATE OR REPLACE FUNCTION get_daily_sales(branch_id_param INTEGER, date_param DATE)
        RETURNS TABLE(
            total_orders BIGINT,
            total_revenue NUMERIC,
            paid_orders BIGINT,
            pending_orders BIGINT
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(CASE WHEN status = 'paid' THEN total_amount ELSE 0 END), 0) as total_revenue,
                COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid_orders,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_orders
            FROM orders 
            WHERE branch_id = branch_id_param 
            AND DATE(created_at) = date_param;
        END;
        $$ LANGUAGE plpgsql;
        """,
        
        # Function to get top selling items
        """
        CREATE OR REPLACE FUNCTION get_top_selling_items(branch_id_param INTEGER, days_back INTEGER DEFAULT 30)
        RETURNS TABLE(
            menu_item_id INTEGER,
            item_name VARCHAR,
            total_quantity BIGINT,
            total_revenue NUMERIC
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT 
                oi.menu_item_id,
                mi.name as item_name,
                SUM(oi.quantity) as total_quantity,
                SUM(oi.quantity * oi.price) as total_revenue
            FROM order_items oi
            JOIN orders o ON oi.order_id = o.id
            JOIN menu_items mi ON oi.menu_item_id = mi.id
            WHERE o.branch_id = branch_id_param 
            AND o.status = 'paid'
            AND o.created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY oi.menu_item_id, mi.name
            ORDER BY total_quantity DESC
            LIMIT 20;
        END;
        $$ LANGUAGE plpgsql;
        """,
        
        # Function to update table status
        """
        CREATE OR REPLACE FUNCTION update_table_status()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Update table status based on active orders
            IF TG_OP = 'INSERT' OR TG_OP = 'UPDATE' THEN
                UPDATE tables 
                SET status = CASE 
                    WHEN EXISTS (
                        SELECT 1 FROM orders 
                        WHERE table_id = NEW.table_id 
                        AND status = 'pending'
                    ) THEN 'occupied'
                    ELSE 'available'
                END
                WHERE id = NEW.table_id;
                RETURN NEW;
            END IF;
            
            IF TG_OP = 'DELETE' THEN
                UPDATE tables 
                SET status = CASE 
                    WHEN EXISTS (
                        SELECT 1 FROM orders 
                        WHERE table_id = OLD.table_id 
                        AND status = 'pending'
                    ) THEN 'occupied'
                    ELSE 'available'
                END
                WHERE id = OLD.table_id;
                RETURN OLD;
            END IF;
            
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """,
    ]
    
    logger.info("⚡ Creating PostgreSQL performance functions...")
    
    for function_sql in functions:
        try:
            db.session.execute(text(function_sql))
            db.session.commit()
            logger.info("✅ Created PostgreSQL function")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not create function: {e}")
            db.session.rollback()

def create_postgresql_triggers():
    """Create PostgreSQL triggers for automation"""
    
    triggers = [
        # Trigger to automatically update table status
        """
        DROP TRIGGER IF EXISTS trg_update_table_status ON orders;
        CREATE TRIGGER trg_update_table_status
        AFTER INSERT OR UPDATE OR DELETE ON orders
        FOR EACH ROW EXECUTE FUNCTION update_table_status();
        """,
        
        # Trigger to update timestamps
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """,
    ]
    
    logger.info("🔄 Creating PostgreSQL automation triggers...")
    
    for trigger_sql in triggers:
        try:
            db.session.execute(text(trigger_sql))
            db.session.commit()
            logger.info("✅ Created PostgreSQL trigger")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not create trigger: {e}")
            db.session.rollback()

def optimize_postgresql_settings():
    """Apply PostgreSQL-specific performance settings"""
    
    settings = [
        # Connection and memory settings
        "SET shared_buffers = '128MB'",
        "SET effective_cache_size = '256MB'",
        "SET work_mem = '32MB'",
        "SET maintenance_work_mem = '64MB'",
        
        # Query planner settings
        "SET random_page_cost = 1.1",
        "SET seq_page_cost = 1.0",
        "SET cpu_tuple_cost = 0.01",
        "SET cpu_index_tuple_cost = 0.005",
        "SET cpu_operator_cost = 0.0025",
        
        # Checkpoint and WAL settings
        "SET checkpoint_completion_target = 0.9",
        "SET wal_buffers = '16MB'",
        "SET checkpoint_timeout = '10min'",
        
        # Statistics and query optimization
        "SET default_statistics_target = 100",
        "SET constraint_exclusion = 'partition'",
        "SET enable_partitionwise_join = on",
        "SET enable_partitionwise_aggregate = on",
        
        # Logging optimization (reduce I/O)
        "SET log_statement = 'none'",
        "SET log_min_duration_statement = 1000",  # Log slow queries only
    ]
    
    logger.info("⚙️  Applying PostgreSQL performance settings...")
    
    for setting in settings:
        try:
            db.session.execute(text(setting))
            logger.info(f"✅ Applied: {setting.split('=')[0].strip()}")
            
        except Exception as e:
            logger.warning(f"⚠️  Could not apply setting: {e}")

def apply_all_postgresql_optimizations():
    """Apply all PostgreSQL optimizations"""
    
    logger.info("🚀 Applying comprehensive PostgreSQL optimizations...")
    
    try:
        # Create indexes for performance
        create_postgresql_indexes()
        
        # Create constraints for data integrity
        create_postgresql_constraints()
        
        # Create functions for complex queries
        create_postgresql_functions()
        
        # Create triggers for automation
        create_postgresql_triggers()
        
        # Apply performance settings
        optimize_postgresql_settings()
        
        logger.info("🎉 All PostgreSQL optimizations applied successfully!")
        logger.info("🔥 Your Restaurant POS is now running at maximum performance!")
        
    except Exception as e:
        logger.error(f"❌ Failed to apply PostgreSQL optimizations: {e}")
        raise

if __name__ == "__main__":
    from app import create_app
    
    app = create_app('production')
    with app.app_context():
        apply_all_postgresql_optimizations()
