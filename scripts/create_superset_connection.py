import os
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from superset.app import create_app
from superset.extensions import db
from superset.models.core import Database


def verify_database(uri: str) -> bool:
    """Check that the PostgreSQL database is reachable."""
    try:
        engine = create_engine(uri)
        with engine.connect() as connection:
            connection.execute("SELECT 1")
        return True
    except SQLAlchemyError as exc:
        print(f"Unable to connect to database: {exc}")
        return False

app = create_app()

with app.app_context():
    uri = os.environ.get("APP_DB_URI")
    if not uri:
        host = os.environ.get("APP_DB_HOST", "db")
        port = os.environ.get("APP_DB_PORT", "5432")
        name = os.environ.get("APP_DB_NAME", "jobsdb")
        user = os.environ.get("APP_DB_USER", "jobuser")
        password = os.environ.get("APP_DB_PASSWORD", "")
        uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
    else:
        name = os.environ.get("APP_DB_NAME", "jobsdb")

    if verify_database(uri):
        db_obj = Database.query.filter_by(database_name=name).first()
        if db_obj:
            db_obj.sqlalchemy_uri = uri
            print(f"Database '{name}' updated in Superset")
        else:
            db_obj = Database(database_name=name, sqlalchemy_uri=uri)
            db.session.add(db_obj)
            print(f"Database '{name}' created in Superset")
        db.session.commit()
    else:
        print("Skipping Superset DB setup due to connection error")
