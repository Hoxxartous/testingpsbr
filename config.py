import os
import logging
import multiprocessing
from datetime import timedelta
from sqlalchemy import event, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool
import sqlite3
import re
from urllib.parse import urlparse

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
    
    # Session configuration for better reliability
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True  # Prevent XSS attacks
    SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF protection
    SESSION_PERMANENT = False  # Don't make sessions permanent by default
    
    # Flask-Login configuration
    REMEMBER_COOKIE_DURATION = timedelta(days=7)  # Remember me duration
    REMEMBER_COOKIE_SECURE = False  # Set to True in production with HTTPS
    REMEMBER_COOKIE_HTTPONLY = True
    
    # Database configuration with SQLite optimizations
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///restaurant_pos.db'
    
    # High-performance database configuration
    @staticmethod
    def get_database_config():
        """Get optimized database configuration based on database type"""
        database_url = os.environ.get('DATABASE_URL', 'sqlite:///restaurant_pos.db')
        
        # Parse database URL to determine type
        parsed = urlparse(database_url)
        is_postgresql = parsed.scheme in ['postgres', 'postgresql']
        
        # Calculate optimal connection pool size based on CPU cores
        cpu_cores = multiprocessing.cpu_count()
        
        if is_postgresql:
            # PostgreSQL optimizations for Render FREE PLAN (limited resources)
            return {
                'poolclass': QueuePool,
                'pool_size': 2,                      # Very small pool for free plan
                'max_overflow': 3,                   # Limited overflow
                'pool_timeout': 60,                  # Longer timeout for free plan
                'pool_recycle': 1800,               # Recycle connections every 30 min
                'pool_pre_ping': True,              # Validate connections (critical for SSL issues)
                'pool_reset_on_return': 'commit',   # Reset connections on return
                
                # PostgreSQL-specific optimizations with SSL stability
                'connect_args': {
                    'connect_timeout': 30,
                    'application_name': 'restaurant_pos',
                    'options': '-c default_transaction_isolation=read_committed -c timezone=UTC',
                    'sslmode': 'prefer',
                    'sslcert': None,
                    'sslkey': None,
                    'sslrootcert': None,
                    'target_session_attrs': 'read-write'
                },
                
                # Engine options for performance
                'echo': False,
                'future': True,
                'execution_options': {
                    'isolation_level': 'READ_COMMITTED',
                    'autocommit': False
                }
            }
        else:
            # SQLite optimizations (fallback)
            return {
                'pool_size': 20,
                'max_overflow': 30,
                'pool_timeout': 30,
                'pool_recycle': 3600,
                'pool_pre_ping': True,
                
                'connect_args': {
                    'timeout': 30,
                    'check_same_thread': False,
                },
                
                'echo': False,
                'future': True,
            }
    
    # Dynamic engine options based on database type
    @classmethod
    def get_engine_options(cls):
        return cls.get_database_config()
    
    # Set default engine options (will be overridden by subclasses)
    SQLALCHEMY_ENGINE_OPTIONS = {}
    
    # Method to handle database initialization
    @classmethod
    def init_app(cls, app):
        # Handle Render's DATABASE_URL format for PostgreSQL
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            if database_url.startswith('postgres://'):
                # Replace postgres:// with postgresql:// as SQLAlchemy requires
                database_url = re.sub(r'^postgres://', 'postgresql://', database_url)
                app.config['SQLALCHEMY_DATABASE_URI'] = database_url
            else:
                app.config['SQLALCHEMY_DATABASE_URI'] = database_url
        
        # Set engine options dynamically based on database type
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = cls.get_database_config()
        
        # Configure database-specific optimizations
        parsed = urlparse(app.config['SQLALCHEMY_DATABASE_URI'])
        if parsed.scheme in ['postgres', 'postgresql']:
            cls._configure_postgresql_optimizations(app)
        else:
            cls._configure_sqlite_optimizations(app)
    
    @staticmethod
    def _configure_sqlite_optimizations(app):
        """Configure SQLite for optimal performance with WAL mode and concurrent access"""
        
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Set SQLite pragmas for optimal performance and concurrency"""
            if 'sqlite' in str(dbapi_connection):
                cursor = dbapi_connection.cursor()
                
                # Enable WAL mode for concurrent reads/writes
                cursor.execute("PRAGMA journal_mode=WAL")
                
                # Optimize SQLite settings for performance
                cursor.execute("PRAGMA synchronous=NORMAL")      # Balance safety/performance
                cursor.execute("PRAGMA cache_size=10000")        # 10MB cache
                cursor.execute("PRAGMA temp_store=MEMORY")       # Store temp tables in memory
                cursor.execute("PRAGMA mmap_size=268435456")     # 256MB memory-mapped I/O
                cursor.execute("PRAGMA page_size=4096")          # Optimal page size
                
                # Optimize for concurrent access
                cursor.execute("PRAGMA busy_timeout=30000")      # 30 second timeout
                cursor.execute("PRAGMA wal_autocheckpoint=1000") # Checkpoint every 1000 pages
                
                # Foreign key constraints
                cursor.execute("PRAGMA foreign_keys=ON")
                
                # Optimize query planner
                cursor.execute("PRAGMA optimize")
                
                cursor.close()
                
                app.logger.info("SQLite optimizations applied: WAL mode enabled, performance settings configured")
        
        @event.listens_for(Engine, "first_connect")
        def receive_first_connect(dbapi_connection, connection_record):
            """Initialize database on first connection"""
            if 'sqlite' in str(dbapi_connection):
                app.logger.info("First SQLite connection established with WAL mode and optimizations")
    
    @staticmethod
    def _configure_postgresql_optimizations(app):
        """Configure PostgreSQL for maximum performance and concurrency"""
        
        @event.listens_for(Engine, "connect")
        def set_postgresql_params(dbapi_connection, connection_record):
            """Set PostgreSQL parameters for optimal performance"""
            try:
                with dbapi_connection.cursor() as cursor:
                    # Connection-level optimizations
                    cursor.execute("SET statement_timeout = '30s'")
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET idle_in_transaction_session_timeout = '60s'")
                    
                    # Performance optimizations
                    cursor.execute("SET work_mem = '32MB'")
                    cursor.execute("SET maintenance_work_mem = '128MB'")
                    cursor.execute("SET effective_cache_size = '256MB'")
                    
                    # Concurrency optimizations
                    cursor.execute("SET max_connections = 200")
                    cursor.execute("SET shared_buffers = '64MB'")
                    
                    # Query optimization
                    cursor.execute("SET random_page_cost = 1.1")
                    cursor.execute("SET seq_page_cost = 1.0")
                    cursor.execute("SET cpu_tuple_cost = 0.01")
                    
                    # Logging optimizations (reduce I/O)
                    cursor.execute("SET log_statement = 'none'")
                    cursor.execute("SET log_min_duration_statement = 1000")  # Log slow queries only
                    
                    # Commit the settings
                    dbapi_connection.commit()
                    
                app.logger.info("PostgreSQL performance optimizations applied")
            except Exception as e:
                app.logger.warning(f"Could not apply PostgreSQL optimizations: {e}")
        
        @event.listens_for(Engine, "first_connect")
        def receive_first_postgresql_connect(dbapi_connection, connection_record):
            """Initialize PostgreSQL connection pool"""
            app.logger.info("First PostgreSQL connection established with performance optimizations")
    
    # Mail configuration (for notifications)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    
    # Security settings (moved to main Config class)
    
    # Application settings
    ITEMS_PER_PAGE = 20
    CURRENCY = 'QAR'
    TIMEZONE = os.environ.get('TIMEZONE') or 'Asia/Qatar'
    
    # Logging configuration
    LOG_TO_STDOUT = os.environ.get('LOG_TO_STDOUT') or True  # Enable by default
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or \
        'sqlite:///restaurant_pos_dev.db'
    LOG_TO_STDOUT = True
    LOG_LEVEL = 'DEBUG'
    
    # Development-specific database optimizations
    @classmethod
    def get_database_config(cls):
        """Get development-optimized database configuration"""
        base_config = super().get_database_config()
        
        # Override for development
        return {
            **base_config,
            'echo': True,  # Enable SQL logging in development
            'pool_size': 5,  # Smaller pool for development
            'max_overflow': 10,
        }

class ProductionConfig(Config):
    DEBUG = False
    
    # Production database configuration - prioritize PostgreSQL for Render
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://user:pass@localhost/restaurant_pos'
    
    # Production-specific optimizations for maximum performance
    @classmethod
    def get_database_config(cls):
        """Get production-optimized database configuration"""
        base_config = super().get_database_config()
        
        # Parse database URL to determine type
        database_url = os.environ.get('DATABASE_URL', cls.SQLALCHEMY_DATABASE_URI)
        parsed = urlparse(database_url)
        is_postgresql = parsed.scheme in ['postgres', 'postgresql']
        
        if is_postgresql:
            # Maximum performance PostgreSQL configuration
            cpu_cores = multiprocessing.cpu_count()
            return {
                **base_config,
                'pool_size': cpu_cores * 6,           # 6 connections per CPU core
                'max_overflow': cpu_cores * 12,       # 12 overflow connections per core
                'pool_timeout': 60,                   # Longer timeout for production
                'pool_recycle': 7200,                # Recycle connections every 2 hours
                'pool_pre_ping': True,
                'pool_reset_on_return': 'commit',
                
                # Production PostgreSQL optimizations
                'connect_args': {
                    'connect_timeout': 10,
                    'application_name': 'restaurant_pos_prod',
                    'options': '-c default_transaction_isolation=read_committed -c timezone=UTC -c statement_timeout=60s'
                },
                
                'echo': False,  # Disable SQL logging in production
                'future': True,
                'execution_options': {
                    'isolation_level': 'READ_COMMITTED',
                    'autocommit': False,
                    'compiled_cache': {}  # Enable query compilation cache
                }
            }
        else:
            # Fallback SQLite configuration with production optimizations
            return {
                **base_config,
                'pool_size': 30,
                'max_overflow': 50,
                'pool_timeout': 60,
                'echo': False,
            }
    
    # Additional production settings
    WTF_CSRF_TIME_LIMIT = None  # No CSRF timeout for long sessions
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)  # 8-hour sessions
    
    # Performance monitoring
    SQLALCHEMY_RECORD_QUERIES = True
    SLOW_DB_QUERY_TIME = 0.5  # Log queries slower than 500ms
    
    @classmethod
    def init_app(cls, app):
        super().init_app(app)
        
        # Production-specific logging
        import logging
        from logging.handlers import RotatingFileHandler
        
        if not app.debug:
            # Set up file logging for production
            if not os.path.exists('logs'):
                os.mkdir('logs')
            
            file_handler = RotatingFileHandler('logs/restaurant_pos.log',
                                             maxBytes=10240000, backupCount=10)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)
            
            app.logger.setLevel(logging.INFO)
            app.logger.info('Restaurant POS startup - Production Mode')

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite://'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}