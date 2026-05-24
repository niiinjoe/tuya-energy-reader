#!/usr/bin/env python3
"""
Tuya Cloud Energy Meter SQLite Data Collector
Downloads raw energy usage data from Tuya Cloud and stores it in SQLite database.
Prevents duplicate entries and creates database if it doesn't exist.
Uses tinytuya to make OpenAPI v2.0 calls for complete data retrieval.
"""

import sys
import json
import argparse
import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import tinytuya

# Global logging level
LOG_LEVEL = 0  # 0=error only, 1=verbose, 2=debug

def log_error(message: str) -> None:
    """Print error message to stderr (always shown)."""
    print(f"ERROR: {message}", file=sys.stderr)

def log_verbose(message: str) -> None:
    """Print verbose message to stderr (shown with --verbose or --debug)."""
    if LOG_LEVEL >= 1:
        print(f"INFO: {message}", file=sys.stderr)

def log_debug(message: str) -> None:
    """Print debug message to stderr (shown only with --debug)."""
    if LOG_LEVEL >= 2:
        print(f"DEBUG: {message}", file=sys.stderr)

def get_credentials():
    """Get Tuya credentials from environment variables."""
    access_id = os.getenv('TUYA_ACCESS_ID')
    access_secret = os.getenv('TUYA_ACCESS_SECRET')

    if not access_id:
        log_error("TUYA_ACCESS_ID environment variable not set")
        sys.exit(1)

    if not access_secret:
        log_error("TUYA_ACCESS_SECRET environment variable not set")
        sys.exit(1)

    return access_id, access_secret

class SQLiteDatabase:
    """SQLite database handler for energy meter data."""

    def __init__(self, db_path: str):
        """Initialize database connection and create table if needed."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute('PRAGMA journal_mode=WAL')  # Better concurrency
        self.create_table()

    def create_table(self):
        """Create energy_readings table if it doesn't exist."""
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS energy_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                total_energy_kwh REAL NOT NULL,
                raw_value REAL NOT NULL,
                iso_timestamp TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(device_id, timestamp)
            )
        ''')

        # Create indexes for better performance
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_device_date
            ON energy_readings(device_id, date)
        ''')

        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_device_timestamp
            ON energy_readings(device_id, timestamp)
        ''')

        self.conn.commit()
        log_debug("Database table and indexes created/verified")

    def insert_readings(self, device_id: str, readings: List[Dict[str, Any]]) -> int:
        """Insert readings into database, avoiding duplicates."""
        if not readings:
            return 0

        inserted_count = 0

        for reading in readings:
            try:
                self.conn.execute('''
                    INSERT OR IGNORE INTO energy_readings
                    (device_id, timestamp, datetime, date, time, total_energy_kwh, raw_value, iso_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    device_id,
                    reading['timestamp'],
                    reading['datetime'].strftime('%Y-%m-%d %H:%M:%S'),
                    reading['date'],
                    reading['time'],
                    reading['total_energy_kwh'],
                    reading['raw_value'],
                    reading['iso_timestamp']
                ))

                if self.conn.total_changes > 0:
                    inserted_count += 1

            except sqlite3.Error as e:
                log_error(f"Error inserting reading {reading['iso_timestamp']}: {e}")

        self.conn.commit()
        log_verbose(f"Inserted {inserted_count} new readings (out of {len(readings)} total)")
        return inserted_count

    def get_reading_count(self, device_id: str) -> int:
        """Get total count of readings for device."""
        cursor = self.conn.execute(
            'SELECT COUNT(*) FROM energy_readings WHERE device_id = ?',
            (device_id,)
        )
        return cursor.fetchone()[0]

    def get_date_range(self, device_id: str) -> tuple:
        """Get earliest and latest dates for device."""
        cursor = self.conn.execute('''
            SELECT MIN(date), MAX(date)
            FROM energy_readings
            WHERE device_id = ?
        ''', (device_id,))

        result = cursor.fetchone()
        return result[0], result[1]

    def close(self):
        """Close database connection."""
        self.conn.close()

class TuyaCloudEnergyMeter:
    """Interface for Tuya Energy Meter using tinytuya with OpenAPI v2.0 endpoints."""

    def __init__(self, access_id: str, access_secret: str, region: str = "us", device_id: str = None):
        """
        Initialize Tuya Cloud connection.

        Args:
            access_id: Tuya Cloud Access ID
            access_secret: Tuya Cloud Access Secret
            region: Cloud region (us, eu, cn, in)
            device_id: Target device ID
        """
        self.device_id = device_id
        self.cloud = tinytuya.Cloud(
            apiRegion=region,
            apiKey=access_id,
            apiSecret=access_secret,
            apiDeviceID=device_id
        )
        log_verbose(f"Initialized Tuya Cloud connection for region: {region}")
        log_debug(f"Target device ID: {device_id}")

    def get_device_info(self) -> Dict[str, Any]:
        """Get device information from cloud."""
        try:
            log_verbose("Retrieving device information from cloud")

            # Use getdevices() to get list of devices, then filter by device_id
            devices = self.cloud.getdevices()
            log_debug(f"Retrieved devices: {json.dumps(devices, indent=2)}")

            # Handle different response formats
            device_list = []
            if isinstance(devices, list):
                # Direct list of devices
                device_list = devices
            elif isinstance(devices, dict) and 'result' in devices:
                # Wrapped in result key
                device_list = devices['result']
            elif isinstance(devices, dict) and devices:
                # Single device or other format
                device_list = [devices]

            if device_list:
                for device in device_list:
                    if device.get('id') == self.device_id:
                        log_verbose(f"Found target device: {device.get('name', 'Unknown')}")
                        log_debug(f"Device details: {json.dumps(device, indent=2)}")
                        return device

                log_error(f"Device {self.device_id} not found in account")
                log_debug(f"Available device IDs: {[d.get('id') for d in device_list if isinstance(d, dict)]}")
                return {}
            else:
                log_error("No devices found in cloud response")
                return {}

        except Exception as e:
            log_error(f"Failed to get device info: {e}")
            return {}

    def get_energy_readings(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get raw energy readings for the specified number of days.

        Args:
            days: Number of days to retrieve (default: 7)

        Returns:
            List of raw energy reading records
        """
        try:
            # Calculate date range
            today = datetime.now().date()
            end_date = datetime.combine(today, datetime.max.time())
            start_date = datetime.combine(today - timedelta(days=days), datetime.min.time())

            log_verbose(f"Requesting energy readings for last {days} days")
            log_verbose(f"Date range: {start_date.date()} to {end_date.date()}")

            # Convert to milliseconds for API
            start_time_ms = int(start_date.timestamp() * 1000)
            end_time_ms = int(end_date.timestamp() * 1000)

            log_debug(f"Calculated timestamps:")
            log_debug(f"  start_time_ms: {start_time_ms} ({datetime.fromtimestamp(start_time_ms/1000)})")
            log_debug(f"  end_time_ms: {end_time_ms} ({datetime.fromtimestamp(end_time_ms/1000)})")

            # Get all total forward energy readings
            total_energy_readings = self._fetch_all_logs(start_time_ms, end_time_ms)

            if not total_energy_readings:
                log_error("No total forward energy readings found")
                return []

            return sorted(total_energy_readings, key=lambda x: x['timestamp'])

        except Exception as e:
            log_error(f"Failed to get energy readings: {e}")
            return []

    def _format_query_params(self, params: Dict[str, Any]) -> str:
        """Format parameters as query string for debugging."""
        param_strings = []
        for key, value in params.items():
            param_strings.append(f"{key}={value}")
        return "&".join(param_strings)

    def _fetch_all_logs(self, start_time_ms: int, end_time_ms: int) -> List[Dict[str, Any]]:
        """Fetch all logs for the specified period using tinytuya with OpenAPI v2.0 endpoint."""
        all_readings = []

        try:
            size = 100  # Use 'size' parameter as per API docs
            last_row_key = None
            page_num = 1

            log_verbose(f"Fetching energy logs from cloud API")
            log_debug(f"Time range: {datetime.fromtimestamp(start_time_ms/1000)} to {datetime.fromtimestamp(end_time_ms/1000)}")

            while True:
                log_verbose(f"Fetching page {page_num}")

                # Prepare parameters for API call
                params = {
                    'codes': 'total_forward_energy',
                    'start_time': start_time_ms,
                    'end_time': end_time_ms,
                    'size': size
                }

                # Add pagination parameter if we have a last_row_key
                if last_row_key:
                    params['last_row_key'] = last_row_key

                # Use tinytuya's cloudrequest method to call the OpenAPI v2.0 endpoint directly
                uri = f"/v2.0/cloud/thing/{self.device_id}/report-logs"

                log_debug(f"Making API request:")
                log_debug(f"  URI: {uri}")
                log_debug(f"  Parameters: {json.dumps(params, indent=2)}")

                result = self.cloud.cloudrequest(uri, query=params)

                log_debug(f"API Response: {json.dumps(result, indent=2)}")

                if not result or not result.get('success', False):
                    log_debug(f"Failed to get logs for page {page_num}: {result}")
                    break

                result_data = result.get('result', {})
                logs = result_data.get('logs', [])
                has_more = result_data.get('has_more', False)
                last_row_key = result_data.get('last_row_key')

                log_verbose(f"Page {page_num}: Retrieved {len(logs)} log entries")
                log_debug(f"Page {page_num}: has_more: {has_more}, last_row_key: {last_row_key}")

                if not logs:
                    log_debug(f"No logs in page {page_num}, stopping pagination")
                    break

                # Parse total energy readings from this page's logs
                page_readings = self._parse_total_energy_readings(logs)

                if page_readings:
                    all_readings.extend(page_readings)
                    log_verbose(f"Page {page_num}: Found {len(page_readings)} energy readings")

                # Check if we have more pages
                if not has_more or not last_row_key:
                    log_verbose(f"No more pages available")
                    break

                page_num += 1

                # Safety check to prevent infinite loops
                if page_num > 100:  # Reasonable limit
                    log_debug(f"Reached maximum page limit (100)")
                    break

            # Remove duplicates and sort by timestamp
            unique_readings = {}
            for reading in all_readings:
                # Use timestamp as key to remove exact duplicates
                timestamp_key = reading['timestamp']
                if timestamp_key not in unique_readings:
                    unique_readings[timestamp_key] = reading

            sorted_readings = sorted(unique_readings.values(), key=lambda x: x['timestamp'])
            log_verbose(f"Retrieved {len(sorted_readings)} unique energy readings from cloud")
            log_debug(f"Total raw readings processed: {len(all_readings)}")

            return sorted_readings

        except Exception as e:
            log_error(f"Error fetching all logs: {e}")
            return []

    def _parse_total_energy_readings(self, logs: List[Dict]) -> List[Dict[str, Any]]:
        """Parse total forward energy readings from Tuya OpenAPI v2.0 logs format."""
        readings = []

        try:
            for log_entry in logs:
                if not isinstance(log_entry, dict):
                    continue

                # Check if this is a total_forward_energy entry
                code = log_entry.get('code')
                if code != 'total_forward_energy':
                    continue

                # Extract timestamp (should be in milliseconds from v2.0 API)
                event_time = log_entry.get('event_time')
                if not event_time:
                    continue

                # Convert timestamp
                try:
                    if event_time > 1e12:  # Milliseconds
                        timestamp = event_time / 1000
                    elif event_time > 1e10:  # Milliseconds (alternative check)
                        timestamp = event_time / 1000
                    else:  # Seconds
                        timestamp = event_time

                    date_obj = datetime.fromtimestamp(timestamp)

                except (ValueError, OSError):
                    log_debug(f"Could not convert timestamp: {event_time}")
                    continue

                # Extract total energy value
                value = log_entry.get('value')
                if value is None:
                    continue

                # Convert value to float
                try:
                    if isinstance(value, str):
                        total_energy_raw = float(value)
                    elif isinstance(value, (int, float)):
                        total_energy_raw = float(value)
                    else:
                        log_debug(f"Unexpected value type: {type(value)} = {value}")
                        continue

                    # Convert based on your device's scale (divide by 100 for scale 2)
                    total_energy_kwh = round(total_energy_raw / 100.0, 3)

                    readings.append({
                        'timestamp': timestamp,
                        'datetime': date_obj,
                        'date': date_obj.strftime('%Y-%m-%d'),
                        'time': date_obj.strftime('%H:%M:%S'),
                        'total_energy_kwh': total_energy_kwh,
                        'iso_timestamp': date_obj.isoformat(),
                        'raw_value': total_energy_raw
                    })

                except (ValueError, TypeError) as e:
                    log_debug(f"Could not convert energy value: {value}, error: {e}")
                    continue

        except Exception as e:
            log_error(f"Error parsing total energy readings: {e}")

        return readings

def main():
    """Main function."""
    global LOG_LEVEL

    parser = argparse.ArgumentParser(
        description='''Download and store raw energy usage data from Tuya Cloud to SQLite database.

Environment Variables Required:
  TUYA_ACCESS_ID     - Tuya Cloud Access ID
  TUYA_ACCESS_SECRET - Tuya Cloud Access Secret

The program prevents duplicate entries and creates the database if it doesn't exist.
Uses tinytuya with OpenAPI v2.0 endpoint for complete data retrieval.

Logging Levels:
  Default: Only errors and final summary
  --verbose: Shows what the program is doing
  --debug: Shows detailed API calls, device info, and responses
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--device-id', required=True,
                       help='Tuya device ID')
    parser.add_argument('--database', default='tuya_energy.db',
                       help='SQLite database file path (default: tuya_energy.db)')
    parser.add_argument('--days', type=int, default=7,
                       help='Number of days to retrieve (default: 7)')
    parser.add_argument('--region', default='us', choices=['us', 'eu', 'cn', 'in'],
                       help='Tuya Cloud region (default: us)')
    parser.add_argument('--verbose', action='store_true',
                       help='Show what the program is doing')
    parser.add_argument('--debug', action='store_true',
                       help='Show detailed debug information including API calls')

    args = parser.parse_args()

    # Set logging level based on arguments
    if args.debug:
        LOG_LEVEL = 2
    elif args.verbose:
        LOG_LEVEL = 1
    else:
        LOG_LEVEL = 0

    # Get credentials from environment variables
    try:
        access_id, access_secret = get_credentials()
    except SystemExit:
        return

    log_verbose(f"Starting Tuya Cloud energy data collection")
    log_debug(f"Access ID: {access_id[:8]}...")  # Only show first 8 characters
    log_debug(f"Device ID: {args.device_id}")
    log_debug(f"Region: {args.region}")
    log_debug(f"Database: {args.database}")
    log_debug(f"Days to retrieve: {args.days}")

    # Initialize database
    db = None
    try:
        log_verbose("Initializing database connection")
        db = SQLiteDatabase(args.database)

        # Show current database status
        existing_count = db.get_reading_count(args.device_id)
        if existing_count > 0:
            date_range = db.get_date_range(args.device_id)
            log_verbose(f"Database contains {existing_count} existing readings for device")
            log_debug(f"Existing data range: {date_range[0]} to {date_range[1]}")
        else:
            log_verbose(f"No existing data found for device {args.device_id}")

        # Initialize cloud energy meter
        log_verbose("Connecting to Tuya Cloud")
        meter = TuyaCloudEnergyMeter(
            access_id=access_id,
            access_secret=access_secret,
            region=args.region,
            device_id=args.device_id
        )

        # Verify device exists
        #device_info = meter.get_device_info()
        #if not device_info:
        #    log_error("Failed to retrieve device information from cloud")
        #    sys.exit(1)

        # Get energy readings
        log_verbose("Retrieving energy readings from cloud")
        energy_readings = meter.get_energy_readings(days=args.days)

        if energy_readings:
            log_verbose(f"Retrieved {len(energy_readings)} readings from cloud")

            # Insert readings into database
            log_verbose("Storing readings in database")
            inserted_count = db.insert_readings(args.device_id, energy_readings)

            # Show final status
            total_count = db.get_reading_count(args.device_id)
            date_range = db.get_date_range(args.device_id)

            # Always show summary (even in quiet mode)
            print(f"SUCCESS: Inserted {inserted_count} new readings", file=sys.stderr)
            print(f"Total readings in database: {total_count}", file=sys.stderr)
            print(f"Data range: {date_range[0]} to {date_range[1]}", file=sys.stderr)

        else:
            log_error(f"No energy data retrieved for the last {args.days} days")
            sys.exit(1)

    except Exception as e:
        log_error(f"Program failed: {e}")
        sys.exit(1)

    finally:
        if db:
            db.close()

if __name__ == "__main__":
    main()
