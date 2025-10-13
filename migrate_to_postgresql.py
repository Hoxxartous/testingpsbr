#!/usr/bin/env python3
"""
Migration script to convert Restaurant POS from SQLite to PostgreSQL
Handles data migration and PostgreSQL-specific optimizations
"""

import os
import sys
import sqlite3
import psycopg
import logging
from urllib.parse import urlparse
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_database_connections():
    """Get SQLite source and PostgreSQL destination connections"""
    
    # SQLite source database
    sqlite_path = os.environ.get('SQLITE_DB_PATH', 'instance/restaurant_pos.db')
    if not os.path.exists(sqlite_path):
        sqlite_path = 'restaurant_pos.db'
    
    if not os.path.exists(sqlite_path):
        logger.error(f"SQLite database not found at {sqlite_path}")
        return None, None
    
    # PostgreSQL destination database
    postgres_url = os.environ.get('DATABASE_URL')
    if not postgres_url:
        logger.error("DATABASE_URL environment variable not set")
        return None, None
    
    # Parse PostgreSQL URL
    if postgres_url.startswith('postgres://'):
        postgres_url = postgres_url.replace('postgres://', 'postgresql://', 1)
    
    try:
        # Connect to SQLite
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row  # Enable column access by name
        logger.info(f"Connected to SQLite database: {sqlite_path}")
        
        # Connect to PostgreSQL
        postgres_conn = psycopg.connect(postgres_url)
        logger.info("Connected to PostgreSQL database")
        
        return sqlite_conn, postgres_conn
        
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None, None

def get_table_schema(sqlite_conn):
    """Get all tables and their schemas from SQLite"""
    cursor = sqlite_conn.cursor()
    
    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    schema_info = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        schema_info[table] = columns
        logger.info(f"Found table: {table} with {len(columns)} columns")
    
    return schema_info

def convert_sqlite_to_postgresql_type(sqlite_type):
    """Convert SQLite data types to PostgreSQL equivalents"""
    type_mapping = {
        'INTEGER': 'INTEGER',
        'TEXT': 'TEXT',
        'REAL': 'REAL',
        'BLOB': 'BYTEA',
        'NUMERIC': 'NUMERIC',
        'BOOLEAN': 'BOOLEAN',
        'DATETIME': 'TIMESTAMP',
        'DATE': 'DATE',
        'TIME': 'TIME',
        'VARCHAR': 'VARCHAR',
        'CHAR': 'CHAR',
        'DECIMAL': 'DECIMAL',
        'FLOAT': 'FLOAT',
        'DOUBLE': 'DOUBLE PRECISION'
    }
    
    sqlite_type_upper = sqlite_type.upper()
    
    # Handle VARCHAR with length
    if 'VARCHAR' in sqlite_type_upper:
        return sqlite_type
    
    # Handle specific patterns
    for sqlite_key, postgres_type in type_mapping.items():
        if sqlite_key in sqlite_type_upper:
            return postgres_type
    
    # Default to TEXT for unknown types
    return 'TEXT'

def create_postgresql_tables(postgres_conn, schema_info):
    """Create tables in PostgreSQL with optimized schema"""
    cursor = postgres_conn.cursor()
    
    for table_name, columns in schema_info.items():
        # Build CREATE TABLE statement
        column_definitions = []
        
        for col in columns:
            col_name = col[1]
            col_type = col[2]
            not_null = col[3]
            default_value = col[4]
            is_pk = col[5]
            
            # Convert SQLite type to PostgreSQL
            pg_type = convert_sqlite_to_postgresql_type(col_type)
            
            # Handle special cases
            if is_pk and pg_type == 'INTEGER':
                pg_type = 'SERIAL PRIMARY KEY'
                col_def = f'"{col_name}" {pg_type}'
            else:
                col_def = f'"{col_name}" {pg_type}'
                
                if not_null:
                    col_def += ' NOT NULL'
                
                if default_value is not None:
                    if pg_type in ['TEXT', 'VARCHAR', 'CHAR']:
                        col_def += f" DEFAULT '{default_value}'"
                    else:
                        col_def += f' DEFAULT {default_value}'
                
                if is_pk and pg_type != 'SERIAL PRIMARY KEY':
                    col_def += ' PRIMARY KEY'
            
            column_definitions.append(col_def)
        
        # Create table
        create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n    ' + ',\n    '.join(column_definitions) + '\n)'
        
        try:
            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
            cursor.execute(create_sql)
            logger.info(f"Created PostgreSQL table: {table_name}")
        except Exception as e:
            logger.error(f"Error creating table {table_name}: {e}")
            logger.error(f"SQL: {create_sql}")
    
    postgres_conn.commit()

def migrate_table_data(sqlite_conn, postgres_conn, table_name):
    """Migrate data from SQLite table to PostgreSQL"""
    sqlite_cursor = sqlite_conn.cursor()
    postgres_cursor = postgres_conn.cursor()
    
    try:
        # Get all data from SQLite table
        sqlite_cursor.execute(f'SELECT * FROM "{table_name}"')
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            logger.info(f"No data to migrate for table: {table_name}")
            return
        
        # Get column names
        column_names = [description[0] for description in sqlite_cursor.description]
        
        # Prepare INSERT statement for PostgreSQL
        placeholders = ', '.join(['%s'] * len(column_names))
        columns_str = ', '.join([f'"{col}"' for col in column_names])
        insert_sql = f'INSERT INTO "{table_name}" ({columns_str}) VALUES ({placeholders})'
        
        # Convert rows to list of tuples for PostgreSQL
        data_to_insert = []
        for row in rows:
            # Handle None values and data type conversions
            converted_row = []
            for value in row:
                if value is None:
                    converted_row.append(None)
                elif isinstance(value, str):
                    converted_row.append(value)
                else:
                    converted_row.append(value)
            data_to_insert.append(tuple(converted_row))
        
        # Insert data in batches
        batch_size = 1000
        for i in range(0, len(data_to_insert), batch_size):
            batch = data_to_insert[i:i + batch_size]
            postgres_cursor.executemany(insert_sql, batch)
        
        postgres_conn.commit()
        logger.info(f"Migrated {len(data_to_insert)} rows for table: {table_name}")
        
    except Exception as e:
        logger.error(f"Error migrating data for table {table_name}: {e}")
        postgres_conn.rollback()

def create_postgresql_indexes(postgres_conn):
    """Create optimized indexes for PostgreSQL"""
    cursor = postgres_conn.cursor()
    
    # Common indexes for restaurant POS system
    indexes = [
        'CREATE INDEX IF NOT EXISTS idx_orders_status ON "order" (status)',
        'CREATE INDEX IF NOT EXISTS idx_orders_created_at ON "order" (created_at)',
        'CREATE INDEX IF NOT EXISTS idx_orders_cashier_id ON "order" (cashier_id)',
        'CREATE INDEX IF NOT EXISTS idx_orders_branch_id ON "order" (branch_id)',
        'CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_item (order_id)',
        'CREATE INDEX IF NOT EXISTS idx_order_items_menu_item_id ON order_item (menu_item_id)',
        'CREATE INDEX IF NOT EXISTS idx_users_branch_id ON "user" (branch_id)',
        'CREATE INDEX IF NOT EXISTS idx_users_role_id ON "user" (role_id)',
        'CREATE INDEX IF NOT EXISTS idx_menu_items_category_id ON menu_item (category_id)',
        'CREATE INDEX IF NOT EXISTS idx_menu_items_branch_id ON menu_item (branch_id)',
        
        # Composite indexes for common queries
        'CREATE INDEX IF NOT EXISTS idx_orders_branch_status ON "order" (branch_id, status)',
        'CREATE INDEX IF NOT EXISTS idx_orders_cashier_created ON "order" (cashier_id, created_at)',
    ]
    
    for index_sql in indexes:
        try:
            cursor.execute(index_sql)
            logger.info(f"Created index: {index_sql.split('idx_')[1].split(' ')[0] if 'idx_' in index_sql else 'unnamed'}")
        except Exception as e:
            logger.warning(f"Could not create index: {e}")
    
    postgres_conn.commit()

def optimize_postgresql_settings(postgres_conn):
    """Apply PostgreSQL-specific optimizations"""
    cursor = postgres_conn.cursor()
    
    # Performance optimizations
    optimizations = [
        "ALTER SYSTEM SET shared_buffers = '128MB'",
        "ALTER SYSTEM SET effective_cache_size = '256MB'",
        "ALTER SYSTEM SET work_mem = '32MB'",
        "ALTER SYSTEM SET maintenance_work_mem = '64MB'",
        "ALTER SYSTEM SET checkpoint_completion_target = 0.9",
        "ALTER SYSTEM SET wal_buffers = '16MB'",
        "ALTER SYSTEM SET default_statistics_target = 100",
        "ALTER SYSTEM SET random_page_cost = 1.1",
        "ALTER SYSTEM SET effective_io_concurrency = 200",
    ]
    
    for optimization in optimizations:
        try:
            cursor.execute(optimization)
            logger.info(f"Applied optimization: {optimization.split('=')[0].split()[-1]}")
        except Exception as e:
            logger.warning(f"Could not apply optimization: {e}")
    
    # Reload configuration
    try:
        cursor.execute("SELECT pg_reload_conf()")
        postgres_conn.commit()
        logger.info("PostgreSQL configuration reloaded")
    except Exception as e:
        logger.warning(f"Could not reload PostgreSQL configuration: {e}")

def main():
    """Main migration function"""
    logger.info("🚀 Starting Restaurant POS SQLite to PostgreSQL migration")
    
    # Get database connections
    sqlite_conn, postgres_conn = get_database_connections()
    if not sqlite_conn or not postgres_conn:
        logger.error("Failed to establish database connections")
        sys.exit(1)
    
    try:
        # Get SQLite schema
        logger.info("📋 Analyzing SQLite database schema...")
        schema_info = get_table_schema(sqlite_conn)
        
        # Create PostgreSQL tables
        logger.info("🏗️  Creating PostgreSQL tables...")
        create_postgresql_tables(postgres_conn, schema_info)
        
        # Migrate data for each table
        logger.info("📦 Migrating data...")
        for table_name in schema_info.keys():
            migrate_table_data(sqlite_conn, postgres_conn, table_name)
        
        # Create indexes
        logger.info("🔍 Creating optimized indexes...")
        create_postgresql_indexes(postgres_conn)
        
        # Apply PostgreSQL optimizations
        logger.info("⚡ Applying PostgreSQL performance optimizations...")
        optimize_postgresql_settings(postgres_conn)
        
        logger.info("✅ Migration completed successfully!")
        logger.info("🎯 Your Restaurant POS is now running on high-performance PostgreSQL!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)
    
    finally:
        # Close connections
        if sqlite_conn:
            sqlite_conn.close()
        if postgres_conn:
            postgres_conn.close()

if __name__ == "__main__":
    main()
