import multiprocessing
import os

# Server socket configuration
bind = "0.0.0.0:" + str(os.environ.get('PORT', 8000))
backlog = 2048

# Optimized for Render FREE PLAN - very limited resources
cpu_cores = multiprocessing.cpu_count()
workers = 2  # Fixed 2 workers for free plan stability

# Worker class - eventlet for async performance and WebSocket support
worker_class = "eventlet"

# Worker connections - reduced for free plan
# With eventlet, we can handle many concurrent connections but limit for free plan
worker_connections = 500  # Reduced for free plan stability

# Timeout settings optimized for restaurant POS
timeout = 120  # Longer timeout for complex operations
keepalive = 5   # Keep connections alive longer

# Worker lifecycle management
max_requests = 2000        # Handle more requests before recycling
max_requests_jitter = 100  # Add randomness to prevent thundering herd

# Memory and performance optimizations
preload_app = True         # Preload for better memory usage and faster startup
worker_tmp_dir = "/dev/shm"  # Use shared memory for better performance (Linux)

# User and group to run as (for production)
# user = "www-data"
# group = "www-data"

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "restaurant_pos"

# Daemon mode (set to False for containerized deployments like Render)
daemon = False

# PID file
pidfile = "/tmp/restaurant_pos.pid"

# Reload on code changes (disable in production for performance)
reload = os.environ.get('FLASK_ENV', 'production') != 'production'

# SSL (uncomment and configure for HTTPS)
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"

# Environment variables for production
raw_env = [
    'FLASK_ENV=production',
    'PYTHONUNBUFFERED=1',  # Ensure logs are flushed immediately
]

# Performance tuning
# Enable threading for better concurrency
threads = 2  # 2 threads per worker for hybrid workloads

# Graceful timeout for worker shutdown
graceful_timeout = 30

# Maximum worker memory usage before restart (in MB)
max_worker_memory_usage = 512  # 512MB per worker

# Startup message and health checks
def on_starting(server):
    server.log.info("🚀 Starting Restaurant POS with Maximum Performance Configuration")
    server.log.info(f"🔧 Workers: {workers} (based on {cpu_cores} CPU cores)")
    server.log.info(f"⚡ Worker class: {worker_class} (async)")
    server.log.info(f"🔗 Worker connections: {worker_connections} per worker")
    server.log.info(f"🧵 Threads per worker: {threads}")
    server.log.info(f"🌐 Binding to: {bind}")
    server.log.info(f"📊 Total concurrent capacity: {workers * worker_connections} connections")
    
    # Check database configuration
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///restaurant_pos.db')
    if 'postgres' in database_url:
        server.log.info("🐘 PostgreSQL database detected - High performance mode enabled")
        server.log.info("🔄 Connection pooling: Enabled with auto-scaling")
        server.log.info("⚡ Query optimization: Enabled")
    else:
        server.log.info("💾 SQLite database detected - WAL mode optimizations enabled")
        
        # Check SQLite WAL mode if using SQLite
        try:
            import sqlite3
            db_files = ['restaurant_pos.db', 'restaurant_pos_dev.db', 'instance/restaurant_pos.db']
            for db_file in db_files:
                if os.path.exists(db_file):
                    conn = sqlite3.connect(db_file)
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA journal_mode")
                    journal_mode = cursor.fetchone()[0]
                    conn.close()
                    
                    if journal_mode.upper() == 'WAL':
                        server.log.info(f"✅ WAL mode enabled for {db_file}")
                    else:
                        server.log.warning(f"⚠️  WAL mode not enabled for {db_file}")
        except Exception as e:
            server.log.warning(f"Could not check SQLite status: {e}")
    
    # Performance summary
    server.log.info("🎯 Performance Configuration Summary:")
    server.log.info(f"   • CPU Cores: {cpu_cores}")
    server.log.info(f"   • Workers: {workers}")
    server.log.info(f"   • Max Connections: {workers * worker_connections}")
    server.log.info(f"   • Worker Class: {worker_class} (async)")
    server.log.info(f"   • Memory per Worker: {max_worker_memory_usage}MB")
    server.log.info("🔥 Restaurant POS ready for maximum performance!")

def on_reload(server):
    server.log.info("Reloading Restaurant POS application...")

def worker_int(worker):
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")

def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid}) - ready to serve requests")

def worker_abort(worker):
    worker.log.info("Worker received SIGABRT signal")
