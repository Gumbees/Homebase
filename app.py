import os
import logging
from logging.handlers import RotatingFileHandler
import sys

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix

# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Configure logging
log_file_path = os.path.join(logs_dir, 'homebase.log')
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Root logger configuration
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_format)
logger.addHandler(console_handler)

# File handler with rotation (max 10MB, keep 5 backup files)
file_handler = RotatingFileHandler(
    log_file_path, 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(log_format)
logger.addHandler(file_handler)

# Create app-specific logger
app_logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy with our base class
db = SQLAlchemy(model_class=Base)

# Create Flask application
app = Flask(__name__)

# Set secret key from environment variable
app.secret_key = os.environ.get("SESSION_SECRET", "development_secret_key")

# Use ProxyFix middleware for proper URL generation with HTTPS
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Configure maximum content length for file uploads (16MB)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Initialize the app with the SQLAlchemy extension
db.init_app(app)

# Create database tables
with app.app_context():
    # Import models to ensure they're recognized by SQLAlchemy
    import models  # noqa: F401
    
    try:
        app_logger.info("Creating database tables...")
        db.create_all()
        app_logger.info("Database tables created successfully")
    except Exception as e:
        app_logger.error(f"Error creating database tables: {e}")

# Import routes after app is initialized
from routes import *  # noqa: F401,E402

# Add utility functions to Jinja environment
@app.context_processor
def utility_processor():
    from routes import determine_object_type_smart
    return dict(determine_object_type_smart=determine_object_type_smart)
