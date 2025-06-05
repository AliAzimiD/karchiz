import os
from superset.app import create_app
from superset.extensions import db
from superset.models.core import Database

app = create_app()

with app.app_context():
    host = os.environ.get("APP_DB_HOST", "db")
    port = os.environ.get("APP_DB_PORT", "5432")
    name = os.environ.get("APP_DB_NAME", "jobsdb")
    user = os.environ.get("APP_DB_USER", "jobuser")
    password = os.environ.get("APP_DB_PASSWORD", "")
    uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"




    if not Database.query.filter_by(database_name=name).first():
        db_obj = Database(database_name=name, sqlalchemy_uri=uri)
        db.session.add(db_obj)
        db.session.commit()
        print(f"Database '{name}' created in Superset")
    else:
        print(f"Database '{name}' already configured")
