from src.db_manager import DatabaseManager


def test_parse_connection_string():
    mgr = DatabaseManager("postgresql://user:pass@localhost:5432/dbname")
    params = mgr._parse_connection_string("postgresql://user:pass@localhost:5432/dbname")
    assert params == {
        "user": "user",
        "password": "pass",
        "host": "localhost",
        "port": 5432,
        "database": "dbname",
    }

