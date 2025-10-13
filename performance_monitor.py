#!/usr/bin/env python3
"""
Performance monitoring script for Restaurant POS on Render
Monitors database performance, connection pools, and system metrics
"""

import os
import time
import psutil
import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from flask import Flask

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PerformanceMonitor:
    def __init__(self, app=None):
        self.app = app
        self.start_time = datetime.utcnow()
        
    def get_database_stats(self):
        """Get PostgreSQL database performance statistics"""
        try:
            from app import db
            
            # Connection pool stats
            pool_stats = {
                'pool_size': db.engine.pool.size(),
                'checked_in': db.engine.pool.checkedin(),
                'checked_out': db.engine.pool.checkedout(),
                'overflow': db.engine.pool.overflow(),
                'invalid': db.engine.pool.invalid()
            }
            
            # Database activity stats
            db_stats_query = """
            SELECT 
                schemaname,
                tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_tuples,
                n_dead_tup as dead_tuples,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables 
            WHERE schemaname = 'public'
            ORDER BY n_live_tup DESC;
            """
            
            result = db.session.execute(text(db_stats_query))
            table_stats = [dict(row._mapping) for row in result]
            
            # Connection stats
            conn_stats_query = """
            SELECT 
                state,
                COUNT(*) as count
            FROM pg_stat_activity 
            WHERE datname = current_database()
            GROUP BY state;
            """
            
            result = db.session.execute(text(conn_stats_query))
            connection_stats = [dict(row._mapping) for row in result]
            
            # Slow queries (if any)
            slow_queries_query = """
            SELECT 
                query,
                calls,
                total_time,
                mean_time,
                rows
            FROM pg_stat_statements 
            WHERE mean_time > 100
            ORDER BY mean_time DESC 
            LIMIT 10;
            """
            
            try:
                result = db.session.execute(text(slow_queries_query))
                slow_queries = [dict(row._mapping) for row in result]
            except:
                slow_queries = []  # pg_stat_statements extension might not be enabled
            
            return {
                'pool_stats': pool_stats,
                'table_stats': table_stats,
                'connection_stats': connection_stats,
                'slow_queries': slow_queries
            }
            
        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return None
    
    def get_system_stats(self):
        """Get system performance statistics"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_stats = {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used,
                'free': memory.free
            }
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_stats = {
                'total': disk.total,
                'used': disk.used,
                'free': disk.free,
                'percent': (disk.used / disk.total) * 100
            }
            
            # Network I/O
            network = psutil.net_io_counters()
            network_stats = {
                'bytes_sent': network.bytes_sent,
                'bytes_recv': network.bytes_recv,
                'packets_sent': network.packets_sent,
                'packets_recv': network.packets_recv
            }
            
            # Process info
            process = psutil.Process()
            process_stats = {
                'pid': process.pid,
                'memory_percent': process.memory_percent(),
                'cpu_percent': process.cpu_percent(),
                'num_threads': process.num_threads(),
                'create_time': datetime.fromtimestamp(process.create_time()),
                'status': process.status()
            }
            
            return {
                'cpu_percent': cpu_percent,
                'cpu_count': cpu_count,
                'memory': memory_stats,
                'disk': disk_stats,
                'network': network_stats,
                'process': process_stats,
                'uptime': datetime.utcnow() - self.start_time
            }
            
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return None
    
    def get_application_stats(self):
        """Get application-specific performance statistics"""
        try:
            from app import db
            from app.models import Order, User, MenuItem, Branch
            
            # Basic counts
            total_orders = Order.query.count()
            total_users = User.query.count()
            total_menu_items = MenuItem.query.count()
            total_branches = Branch.query.count()
            
            # Recent activity (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(days=1)
            recent_orders = Order.query.filter(Order.created_at >= yesterday).count()
            
            # Orders by status
            orders_by_status = db.session.execute(text("""
                SELECT status, COUNT(*) as count 
                FROM orders 
                GROUP BY status
            """)).fetchall()
            
            # Revenue today
            today = datetime.utcnow().date()
            today_revenue = db.session.execute(text("""
                SELECT COALESCE(SUM(total_amount), 0) as revenue
                FROM orders 
                WHERE DATE(created_at) = :today 
                AND status = 'paid'
            """), {'today': today}).scalar()
            
            return {
                'total_orders': total_orders,
                'total_users': total_users,
                'total_menu_items': total_menu_items,
                'total_branches': total_branches,
                'recent_orders_24h': recent_orders,
                'orders_by_status': [dict(row._mapping) for row in orders_by_status],
                'today_revenue': float(today_revenue) if today_revenue else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error getting application stats: {e}")
            return None
    
    def check_performance_health(self):
        """Check overall system health and performance"""
        health_status = {
            'overall': 'healthy',
            'issues': [],
            'recommendations': []
        }
        
        # Get stats
        system_stats = self.get_system_stats()
        db_stats = self.get_database_stats()
        
        if system_stats:
            # Check CPU usage
            if system_stats['cpu_percent'] > 90:
                health_status['issues'].append('High CPU usage detected')
                health_status['recommendations'].append('Consider upgrading to higher tier plan')
                health_status['overall'] = 'warning'
            
            # Check memory usage
            if system_stats['memory']['percent'] > 90:
                health_status['issues'].append('High memory usage detected')
                health_status['recommendations'].append('Monitor memory leaks or upgrade plan')
                health_status['overall'] = 'warning'
            
            # Check disk usage
            if system_stats['disk']['percent'] > 85:
                health_status['issues'].append('High disk usage detected')
                health_status['recommendations'].append('Clean up logs or upgrade storage')
                health_status['overall'] = 'warning'
        
        if db_stats and db_stats['pool_stats']:
            pool = db_stats['pool_stats']
            
            # Check connection pool usage
            pool_usage = (pool['checked_out'] / pool['pool_size']) * 100 if pool['pool_size'] > 0 else 0
            if pool_usage > 80:
                health_status['issues'].append('High database connection pool usage')
                health_status['recommendations'].append('Optimize database queries or increase pool size')
                health_status['overall'] = 'warning'
            
            # Check for dead tuples (needs vacuum)
            if db_stats['table_stats']:
                for table in db_stats['table_stats']:
                    if table['dead_tuples'] and table['live_tuples']:
                        dead_ratio = table['dead_tuples'] / table['live_tuples']
                        if dead_ratio > 0.2:  # More than 20% dead tuples
                            health_status['issues'].append(f"Table {table['tablename']} needs vacuum")
                            health_status['recommendations'].append('Run VACUUM ANALYZE on database')
                            health_status['overall'] = 'warning'
        
        if health_status['issues']:
            if len(health_status['issues']) > 3:
                health_status['overall'] = 'critical'
        
        return health_status
    
    def generate_performance_report(self):
        """Generate comprehensive performance report"""
        logger.info("🔍 Generating performance report...")
        
        report = {
            'timestamp': datetime.utcnow().isoformat(),
            'system_stats': self.get_system_stats(),
            'database_stats': self.get_database_stats(),
            'application_stats': self.get_application_stats(),
            'health_check': self.check_performance_health()
        }
        
        return report
    
    def print_performance_summary(self):
        """Print a formatted performance summary"""
        report = self.generate_performance_report()
        
        print("\n" + "="*60)
        print("🔥 RESTAURANT POS PERFORMANCE REPORT")
        print("="*60)
        
        # System Stats
        if report['system_stats']:
            sys_stats = report['system_stats']
            print(f"\n📊 SYSTEM PERFORMANCE:")
            print(f"   • CPU Usage: {sys_stats['cpu_percent']:.1f}% ({sys_stats['cpu_count']} cores)")
            print(f"   • Memory Usage: {sys_stats['memory']['percent']:.1f}% ({sys_stats['memory']['used']//1024//1024}MB used)")
            print(f"   • Disk Usage: {sys_stats['disk']['percent']:.1f}% ({sys_stats['disk']['used']//1024//1024//1024}GB used)")
            print(f"   • Uptime: {sys_stats['uptime']}")
        
        # Database Stats
        if report['database_stats'] and report['database_stats']['pool_stats']:
            db_stats = report['database_stats']
            pool = db_stats['pool_stats']
            print(f"\n🐘 DATABASE PERFORMANCE:")
            print(f"   • Connection Pool: {pool['checked_out']}/{pool['pool_size']} active")
            print(f"   • Pool Usage: {(pool['checked_out']/pool['pool_size']*100):.1f}%")
            print(f"   • Overflow Connections: {pool['overflow']}")
            print(f"   • Invalid Connections: {pool['invalid']}")
            
            if db_stats['table_stats']:
                print(f"   • Active Tables: {len(db_stats['table_stats'])}")
                top_table = db_stats['table_stats'][0] if db_stats['table_stats'] else None
                if top_table:
                    print(f"   • Largest Table: {top_table['tablename']} ({top_table['live_tuples']} rows)")
        
        # Application Stats
        if report['application_stats']:
            app_stats = report['application_stats']
            print(f"\n🏪 APPLICATION METRICS:")
            print(f"   • Total Orders: {app_stats['total_orders']}")
            print(f"   • Recent Orders (24h): {app_stats['recent_orders_24h']}")
            print(f"   • Today's Revenue: {app_stats['today_revenue']:.2f} QAR")
            print(f"   • Active Users: {app_stats['total_users']}")
            print(f"   • Menu Items: {app_stats['total_menu_items']}")
            print(f"   • Branches: {app_stats['total_branches']}")
        
        # Health Check
        health = report['health_check']
        status_emoji = {
            'healthy': '✅',
            'warning': '⚠️',
            'critical': '❌'
        }
        
        print(f"\n🏥 HEALTH STATUS: {status_emoji.get(health['overall'], '❓')} {health['overall'].upper()}")
        
        if health['issues']:
            print(f"\n⚠️  ISSUES DETECTED:")
            for issue in health['issues']:
                print(f"   • {issue}")
        
        if health['recommendations']:
            print(f"\n💡 RECOMMENDATIONS:")
            for rec in health['recommendations']:
                print(f"   • {rec}")
        
        if health['overall'] == 'healthy':
            print(f"\n🎉 System is running optimally!")
            print(f"🔥 Maximum performance configuration is working perfectly!")
        
        print("\n" + "="*60)
        
        return report

def main():
    """Main monitoring function"""
    try:
        # Create Flask app context
        from app import create_app
        app = create_app('production')
        
        with app.app_context():
            monitor = PerformanceMonitor(app)
            
            # Print performance summary
            report = monitor.print_performance_summary()
            
            # Save report to file if needed
            if os.environ.get('SAVE_PERFORMANCE_REPORT'):
                import json
                timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                filename = f'performance_report_{timestamp}.json'
                
                with open(filename, 'w') as f:
                    json.dump(report, f, indent=2, default=str)
                
                logger.info(f"📄 Performance report saved to {filename}")
            
    except Exception as e:
        logger.error(f"❌ Performance monitoring failed: {e}")

if __name__ == "__main__":
    main()
