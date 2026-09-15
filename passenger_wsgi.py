#!/usr/bin/env python3
"""
passenger_wsgi.py - Entry point for Passenger WSGI
This file is required for deploying Flask apps on shared hosting with Passenger
"""

import sys
import os

# Derive paths relative to this file's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, 'src'))
sys.path.insert(0, BASE_DIR)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Import the Flask application
from src.app import app as application
