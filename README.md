# Tuya Energy Reader

A Python-based utility to collect and report energy consumption data from Tuya-compatible smart devices.

## Features
- **Data Collection:** Periodically polls energy usage data from configured Tuya devices.
- **Data Storage:** Stores collected data in a local SQLite database (`tuya_energy.db`).
- **Reporting:** Provides functionality to generate reports based on the collected data.

## Prerequisites
- Python 3.x
- `pip` for dependency management

## Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd tuya-energy-reader
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the template environment file and add your credentials:
   ```bash
   cp .env.example .env
   ```
   Open `.env` in a text editor and fill in your Tuya API keys and Device ID.

## Usage

### Collecting Data
Run the collector script to fetch current energy readings:
```bash
./collector.sh
```
Or directly:
```bash
python3 collector.py
```

### Reporting
Run the reporter script to view/process the stored energy data:
```bash
./reporter.sh
```
Or directly:
```bash
python3 reporter.py
```

## License
This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## AI Note
This code was developed with the assistance of AI.
