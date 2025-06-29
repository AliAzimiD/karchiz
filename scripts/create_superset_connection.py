import logging
import os

try:
    import psycopg2  # noqa: F401
except ImportError:
    import sys
    print(
        "ERROR: psycopg2-binary is installed but not available to the current Python environment.\n"
        "Try running:\n"
        "  pip install --user psycopg2-binary\n"
        "Or ensure your PYTHONPATH includes the user site-packages directory.\n"
        "If running inside a container, restart the container after installing.",
        file=sys.stderr,
    )
    sys.exit(1)

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from superset.app import create_app
from superset.extensions import db


def get_logger(name: str = "superset_setup") -> logging.Logger:
    """Return a basic logger configured for console output."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = get_logger("superset_setup")


def verify_database(uri: str) -> bool:
    """Check that the PostgreSQL database is reachable and driver is installed."""
    try:
        engine = create_engine(uri)
        with engine.connect() as connection:
            connection.execute("SELECT 1")
        return True
    except ModuleNotFoundError as exc:
        logger.error(
            "Database driver not found: %s. "
            "Make sure psycopg2 is installed in your Superset environment.",
            exc.name,
        )
        return False
    except SQLAlchemyError as exc:
        logger.error(f"Unable to connect to database: {exc}")
        return False


app = create_app()

with app.app_context():
    from superset.models.core import Database

    uri = os.environ.get("APP_DB_URI")
    if not uri:
        host = os.environ.get("APP_DB_HOST", "db")
        port = os.environ.get("APP_DB_PORT", "5432")
        name = os.environ.get("APP_DB_NAME", "jobsdb")
        user = os.environ.get("APP_DB_USER", "jobuser")
        password = os.environ.get("APP_DB_PASSWORD", "your_secure_db_password")
        uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    else:
        name = os.environ.get("APP_DB_NAME", "jobsdb")

    if verify_database(uri):
        session = db.session
        db_obj = session.query(Database).filter_by(database_name=name).first()
        if db_obj:
            db_obj.sqlalchemy_uri = uri
            logger.info(f"Database '{name}' updated in Superset")
        else:
            db_obj = Database(database_name=name, sqlalchemy_uri=uri)
            session.add(db_obj)
            logger.info(f"Database '{name}' created in Superset")
        session.commit()
    else:
        logger.error("Skipping Superset DB setup due to connection error")
