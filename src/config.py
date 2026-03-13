"""
config.py - Configuration management for arXiv frontend

Loads configuration from environment variables (.env file)
"""

import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'arxiv_user'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME', 'arxiv_frontend'),
    'charset': os.getenv('DB_CHARSET', 'utf8mb4')
}

# Flask configuration
FLASK_CONFIG = {
    'SECRET_KEY': os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production'),
    'DEBUG': os.getenv('FLASK_DEBUG', 'False').lower() == 'true',
    'PREFERRED_URL_SCHEME': os.getenv('PREFERRED_URL_SCHEME', 'http'),
}

# Secret key for triggering paper fetches via URL
FETCH_SECRET = os.getenv('FETCH_SECRET', '')

# Admin UI password
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

# ORCID iD that is automatically granted admin on login
ADMIN_ORCID = os.getenv('ADMIN_ORCID', '')

# ORCID OAuth credentials (register at https://orcid.org/developer-tools)
ORCID_CLIENT_ID     = os.getenv('ORCID_CLIENT_ID', '')
ORCID_CLIENT_SECRET = os.getenv('ORCID_CLIENT_SECRET', '')

def validate_config():
    """Validate that required configuration is set."""
    errors = []
    if not DB_CONFIG['password']:
        errors.append("DB_PASSWORD not set")
    if not ADMIN_PASSWORD:
        errors.append("ADMIN_PASSWORD not set (admin UI will be inaccessible)")
    if not FETCH_SECRET:
        errors.append("FETCH_SECRET not set (paper fetch endpoint disabled)")
    if FLASK_CONFIG['SECRET_KEY'] == 'dev-secret-key-change-in-production':
        errors.append("FLASK_SECRET_KEY is using the insecure default — set it in .env")
    critical = [e for e in errors if 'DB_PASSWORD' in e]
    warnings = [e for e in errors if e not in critical]
    if critical:
        raise ValueError(
            "Configuration error: " + "; ".join(critical) +
            "\nPlease create a .env file based on .env.example"
        )
    for w in warnings:
        import sys
        print(f"WARNING: {w}", file=sys.stderr)

if __name__ == '__main__':
    # Test configuration
    try:
        validate_config()
        print("Configuration loaded successfully:")
        print(f"  DB Host: {DB_CONFIG['host']}")
        print(f"  DB User: {DB_CONFIG['user']}")
        print(f"  DB Name: {DB_CONFIG['database']}")
        print(f"  Password: {'*' * len(DB_CONFIG['password'])}")
    except ValueError as e:
        print(f"Configuration error: {e}")