"""Raw database connection helper."""

import psycopg2
from quant.core.config import config


def get_raw_connection():
    """Get a raw psycopg2 connection."""
    return psycopg2.connect(config.database_url)
