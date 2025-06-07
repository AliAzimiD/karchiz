import asyncio
from main import load_config
from src.db_manager import DatabaseManager
from src.health import HealthCheck


async def main() -> None:
    config = load_config()
    db_conn = config["database"]["connection_string"]
    db_manager = DatabaseManager(connection_string=db_conn)
    await db_manager.initialize()
    health = HealthCheck(db_manager)
    host = config["app"].get("health_host", "0.0.0.0")
    port = config["app"].get("health_port", 8080)
    runner, _ = await health.start(host=host, port=port)
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
