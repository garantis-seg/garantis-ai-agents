"""
Service Sync Tracker - Track service execution status in PostgreSQL.

All services can use this to record when they start, finish, and their results.

Table schema:
    service_sync_status (
        service_name VARCHAR(50) PRIMARY KEY,
        last_sync TIMESTAMP,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        status VARCHAR(20),  -- 'running', 'completed', 'failed'
        records_processed INTEGER,
        error_message TEXT,
        updated_at TIMESTAMP
    )

Usage:
    from garantis_shared.sync_tracker import SyncTracker

    tracker = SyncTracker(service_name='service-3-html-parser', db_pool=pool)

    # At start of service
    tracker.start()

    # During processing (optional)
    tracker.update_progress(records_processed=100)

    # At end of service (success)
    tracker.complete(records_processed=500)

    # At end of service (failure)
    tracker.fail(error_message="Connection timeout")
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class SyncTracker:
    """Track service execution status in PostgreSQL."""

    def __init__(self, service_name: str, db_pool):
        """
        Initialize tracker.

        Args:
            service_name: Unique identifier for this service
            db_pool: psycopg2 connection pool
        """
        self.service_name = service_name
        self.pool = db_pool
        self._started_at: Optional[datetime] = None

    def _ensure_table_exists(self) -> None:
        """Create the sync status table if it doesn't exist."""
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS service_sync_status (
                    service_name VARCHAR(50) PRIMARY KEY,
                    last_sync TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'completed',
                    records_processed INTEGER DEFAULT 0,
                    error_message TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
        finally:
            self.pool.putconn(conn)

    def start(self) -> None:
        """Record that this service has started running."""
        self._started_at = datetime.now()
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO service_sync_status (
                    service_name, started_at, status, records_processed, error_message, updated_at
                ) VALUES (%s, %s, 'running', 0, NULL, NOW())
                ON CONFLICT (service_name) DO UPDATE SET
                    started_at = EXCLUDED.started_at,
                    status = 'running',
                    records_processed = 0,
                    error_message = NULL,
                    updated_at = NOW()
            """, (self.service_name, self._started_at))
            conn.commit()
            logger.info(f"{self.service_name} started at {self._started_at}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record start: {e}")
        finally:
            self.pool.putconn(conn)

    def update_progress(self, records_processed: int) -> None:
        """Update progress during processing."""
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE service_sync_status
                SET records_processed = %s, updated_at = NOW()
                WHERE service_name = %s
            """, (records_processed, self.service_name))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update progress: {e}")
        finally:
            self.pool.putconn(conn)

    def complete(self, records_processed: int = 0) -> None:
        """Record successful completion."""
        finished_at = datetime.now()
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE service_sync_status
                SET
                    last_sync = %s,
                    finished_at = %s,
                    status = 'completed',
                    records_processed = %s,
                    error_message = NULL,
                    updated_at = NOW()
                WHERE service_name = %s
            """, (finished_at, finished_at, records_processed, self.service_name))
            conn.commit()

            duration = (finished_at - self._started_at).total_seconds() if self._started_at else 0
            logger.info(f"{self.service_name} completed: {records_processed} records in {duration:.1f}s")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record completion: {e}")
        finally:
            self.pool.putconn(conn)

    def fail(self, error_message: str, records_processed: int = 0) -> None:
        """Record failure."""
        finished_at = datetime.now()
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE service_sync_status
                SET
                    finished_at = %s,
                    status = 'failed',
                    records_processed = %s,
                    error_message = %s,
                    updated_at = NOW()
                WHERE service_name = %s
            """, (finished_at, records_processed, error_message[:500], self.service_name))
            conn.commit()
            logger.error(f"{self.service_name} failed: {error_message}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record failure: {e}")
        finally:
            self.pool.putconn(conn)

    def get_status(self, service_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get status of a service.

        Args:
            service_name: Service to check (defaults to self)

        Returns:
            Dict with service status or None if not found
        """
        service = service_name or self.service_name
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_name, last_sync, started_at, finished_at,
                       status, records_processed, error_message, updated_at
                FROM service_sync_status
                WHERE service_name = %s
            """, (service,))
            row = cursor.fetchone()
            if row:
                return {
                    'service_name': row[0],
                    'last_sync': row[1],
                    'started_at': row[2],
                    'finished_at': row[3],
                    'status': row[4],
                    'records_processed': row[5],
                    'error_message': row[6],
                    'updated_at': row[7]
                }
            return None
        finally:
            self.pool.putconn(conn)

    def is_service_running(self, service_name: str) -> bool:
        """Check if another service is currently running."""
        status = self.get_status(service_name)
        return status is not None and status.get('status') == 'running'

    def get_all_statuses(self) -> List[Dict[str, Any]]:
        """Get status of all services."""
        conn = self.pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT service_name, last_sync, started_at, finished_at,
                       status, records_processed, error_message, updated_at
                FROM service_sync_status
                ORDER BY service_name
            """)
            rows = cursor.fetchall()
            return [
                {
                    'service_name': row[0],
                    'last_sync': row[1],
                    'started_at': row[2],
                    'finished_at': row[3],
                    'status': row[4],
                    'records_processed': row[5],
                    'error_message': row[6],
                    'updated_at': row[7]
                }
                for row in rows
            ]
        finally:
            self.pool.putconn(conn)

    def get_last_sync(self, service_name: Optional[str] = None) -> Optional[datetime]:
        """Get last successful sync timestamp for a service."""
        status = self.get_status(service_name)
        return status.get('last_sync') if status else None
