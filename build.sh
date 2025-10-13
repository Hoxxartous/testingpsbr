#!/bin/bash
# Build script for Render deployment with PostgreSQL optimization

set -e  # Exit on any error

echo "🚀 Starting Restaurant POS build for Render deployment..."
echo "🐘 PostgreSQL + ⚡ Maximum Performance Configuration"

# Update pip and install dependencies
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Verify PostgreSQL driver installation
echo "🔍 Verifying PostgreSQL driver..."
python -c "
try:
    import psycopg2
    print('✅ PostgreSQL driver (psycopg2) installed successfully')
except ImportError:
    try:
        import psycopg
        print('✅ PostgreSQL driver (psycopg) installed successfully')
    except ImportError:
        print('❌ No PostgreSQL driver found')
        exit(1)
"

# Verify eventlet installation for async performance
echo "🔍 Verifying async libraries..."
python -c "import eventlet; print('✅ Eventlet installed successfully')"

# Set up environment for production
export FLASK_ENV=production
export PYTHONUNBUFFERED=1

# Create necessary directories
echo "📁 Creating application directories..."
mkdir -p logs
mkdir -p instance
mkdir -p migrations

# Run deployment script if DATABASE_URL is available
if [ -n "$DATABASE_URL" ]; then
    echo "🗄️  Database URL detected, running deployment setup..."
    python deploy_to_render.py
else
    echo "⚠️  DATABASE_URL not set, skipping database setup"
    echo "   Database will be set up on first run"
fi

# Collect static files (if needed)
echo "📄 Preparing static files..."
# Add any static file collection here if needed

echo "✅ Build completed successfully!"
echo "🎯 Restaurant POS is ready for maximum performance deployment!"
