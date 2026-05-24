#!/usr/bin/env python3
"""
Monthly Energy Usage Summary Generator
Reads raw energy data from SQLite database and generates monthly summary CSV.
Each row represents one month with daily kWh usage in columns.
Uses the same calculation logic as the original script.
"""

import sys
import csv
import argparse
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
import calendar

# Global verbose flag
VERBOSE = False

def log_debug(message: str) -> None:
    """Print debug message to stderr if verbose mode is enabled."""
    if VERBOSE:
        print(f"DEBUG: {message}", file=sys.stderr)

def log_error(message: str) -> None:
    """Print error message to stderr."""
    print(f"ERROR: {message}", file=sys.stderr)

class EnergyDataProcessor:
    """Process energy data from SQLite database."""

    def __init__(self, db_path: str):
        """Initialize database connection."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Enable column access by name

    def get_all_readings(self, device_id: str) -> List[Dict[str, Any]]:
        """Get all energy readings for a device, sorted by timestamp."""
        cursor = self.conn.execute('''
            SELECT * FROM energy_readings
            WHERE device_id = ?
            ORDER BY timestamp
        ''', (device_id,))

        readings = []
        for row in cursor:
            readings.append({
                'timestamp': row['timestamp'],
                'datetime': datetime.fromisoformat(row['iso_timestamp']),
                'date': row['date'],
                'time': row['time'],
                'total_energy_kwh': row['total_energy_kwh'],
                'raw_value': row['raw_value'],
                'iso_timestamp': row['iso_timestamp']
            })

        return readings

    def calculate_daily_usage(self, readings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Calculate daily usage from total energy readings.
        Uses the same logic as the original script.
        """
        daily_usage = []

        try:
            if not readings:
                return daily_usage

            log_debug(f"Calculating daily usage from {len(readings)} total energy readings")

            # Group readings by date
            readings_by_date = defaultdict(list)
            for reading in readings:
                date = reading['date']
                readings_by_date[date].append(reading)

            # Sort dates
            sorted_dates = sorted(readings_by_date.keys())
            log_debug(f"Found readings for dates: {sorted_dates}")

            prev_day_last_reading = None

            for date in sorted_dates:
                day_readings = sorted(readings_by_date[date], key=lambda x: x['timestamp'])

                if not day_readings:
                    continue

                first_reading = day_readings[0]
                last_reading = day_readings[-1]

                # Method 1: Use previous day's last reading if available
                if prev_day_last_reading is not None:
                    start_total = prev_day_last_reading['total_energy_kwh']
                    end_total = last_reading['total_energy_kwh']
                    start_time = prev_day_last_reading['iso_timestamp']
                    end_time = last_reading['iso_timestamp']

                    daily_kwh = end_total - start_total
                    calculation_method = "previous_day_to_current"

                    log_debug(f"Date {date}: Using previous day method - {daily_kwh:.2f} kWh (from {start_total:.2f} to {end_total:.2f})")

                # Method 2: Use within-day calculation (first to last reading of the day)
                else:
                    if len(day_readings) > 1:
                        start_total = first_reading['total_energy_kwh']
                        end_total = last_reading['total_energy_kwh']
                        start_time = first_reading['iso_timestamp']
                        end_time = last_reading['iso_timestamp']

                        daily_kwh = end_total - start_total
                        calculation_method = "within_day"

                        log_debug(f"Date {date}: Using within-day method - {daily_kwh:.2f} kWh (from {start_total:.2f} to {end_total:.2f})")
                    else:
                        # Only one reading for the day - can't calculate usage
                        log_debug(f"Date {date}: Only one reading available, cannot calculate daily usage")
                        prev_day_last_reading = last_reading
                        continue

                # Sanity check: daily usage should be positive and reasonable (< 1000 kWh/day)
                if 0 <= daily_kwh <= 1000:
                    daily_usage.append({
                        'date': date,
                        'energy_kwh': round(daily_kwh, 2),
                        'timestamp': last_reading['iso_timestamp'],
                        'start_total': round(start_total, 2),
                        'end_total': round(end_total, 2),
                        'start_time': start_time,
                        'end_time': end_time,
                        'calculation_method': calculation_method,
                        'readings_count': len(day_readings)
                    })
                else:
                    log_debug(f"Skipping date {date}: unrealistic daily usage {daily_kwh:.2f} kWh")
                    log_debug(f"  Start total: {start_total:.2f} kWh at {start_time}")
                    log_debug(f"  End total: {end_total:.2f} kWh at {end_time}")

                # Update previous day's last reading for next iteration
                prev_day_last_reading = last_reading

            log_debug(f"Calculated daily usage for {len(daily_usage)} days")

            # Show calculation methods used
            if daily_usage:
                method_counts = defaultdict(int)
                for usage in daily_usage:
                    method = usage['calculation_method']
                    method_counts[method] += 1

                for method, count in method_counts.items():
                    log_debug(f"  {method}: {count} days")

        except Exception as e:
            log_error(f"Error calculating daily usage: {e}")

        return daily_usage

    def group_by_month(self, daily_usage: List[Dict[str, Any]]) -> Dict[str, Dict[int, float]]:
        """Group daily usage by month and day."""
        monthly_data = defaultdict(dict)

        for usage in daily_usage:
            date_obj = datetime.strptime(usage['date'], '%Y-%m-%d').date()
            month_key = date_obj.strftime('%Y-%m')
            day = date_obj.day

            monthly_data[month_key][day] = usage['energy_kwh']

        return monthly_data

    def close(self):
        """Close database connection."""
        self.conn.close()

def generate_monthly_csv(monthly_data: Dict[str, Dict[int, float]]) -> None:
    """Generate CSV output with monthly summaries."""
    if not monthly_data:
        log_error("No monthly data to output")
        return

    # Create header with all possible days (1-31)
    fieldnames = ['month'] + [f'day_{i:02d}' for i in range(1, 32)] + ['total_kwh', 'days_with_data']

    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()

    # Sort months
    sorted_months = sorted(monthly_data.keys())

    for month in sorted_months:
        daily_data = monthly_data[month]

        # Create row data
        row = {'month': month}

        # Add daily values
        total_kwh = 0.0
        days_with_data = 0

        for day in range(1, 32):
            day_key = f'day_{day:02d}'
            if day in daily_data:
                kwh_value = daily_data[day]
                row[day_key] = f"{kwh_value:.2f}"
                total_kwh += kwh_value
                days_with_data += 1
            else:
                row[day_key] = ''  # Empty for days without data

        # Add summary columns
        row['total_kwh'] = f"{total_kwh:.2f}"
        row['days_with_data'] = days_with_data

        writer.writerow(row)

    log_debug(f"Output {len(sorted_months)} monthly summaries to CSV")

def main():
    """Main function."""
    global VERBOSE

    parser = argparse.ArgumentParser(
        description='''Generate monthly energy usage summary from SQLite database.

Reads raw energy data from SQLite database and outputs CSV with monthly summaries.
Each row represents one month with daily kWh usage in columns.
Uses the same calculation logic as the original energy meter script.

Output Format:
- month: YYYY-MM format
- day_01 to day_31: Daily kWh usage (empty if no data)
- total_kwh: Sum of all days in the month
- days_with_data: Number of days with actual data
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--device-id', required=True,
                       help='Tuya device ID')
    parser.add_argument('--database', default='tuya_energy.db',
                       help='SQLite database file path (default: tuya_energy.db)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose debug output')

    args = parser.parse_args()

    # Set global verbose flag
    VERBOSE = args.verbose

    log_debug(f"Starting monthly energy usage summary generation")
    log_debug(f"Device ID: {args.device_id}")
    log_debug(f"Database: {args.database}")

    processor = None
    try:
        # Initialize database processor
        processor = EnergyDataProcessor(args.database)

        # Get all readings for the device
        log_debug("Retrieving all energy readings from database...")
        readings = processor.get_all_readings(args.device_id)

        if not readings:
            log_error(f"No energy readings found for device {args.device_id}")
            sys.exit(1)

        log_debug(f"Found {len(readings)} raw readings")

        # Calculate daily usage
        log_debug("Calculating daily usage...")
        daily_usage = processor.calculate_daily_usage(readings)

        if not daily_usage:
            log_error("No daily usage could be calculated")
            sys.exit(1)

        log_debug(f"Calculated daily usage for {len(daily_usage)} days")

        # Group by month
        log_debug("Grouping data by month...")
        monthly_data = processor.group_by_month(daily_usage)

        if not monthly_data:
            log_error("No monthly data could be generated")
            sys.exit(1)

        log_debug(f"Generated monthly summaries for {len(monthly_data)} months")

        # Show month summary in verbose mode
        if VERBOSE:
            for month in sorted(monthly_data.keys()):
                days_count = len(monthly_data[month])
                total_kwh = sum(monthly_data[month].values())
                log_debug(f"Month {month}: {days_count} days, {total_kwh:.2f} kWh total")

        # Generate CSV output
        generate_monthly_csv(monthly_data)

    except FileNotFoundError:
        log_error(f"Database file not found: {args.database}")
        sys.exit(1)
    except sqlite3.Error as e:
        log_error(f"Database error: {e}")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        if processor:
            processor.close()

if __name__ == "__main__":
    main()
