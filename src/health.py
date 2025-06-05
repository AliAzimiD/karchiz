import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional, Tuple

import aiohttp
import psutil
from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from .db_manager import DatabaseManager
from .log_setup import get_logger

logger = get_logger("health_check")


class HealthCheck:
    """
    Provides a basic health check and metrics API using aiohttp.

    Attributes:
        db_manager (DatabaseManager): An instance managing database connectivity.
        app (web.Application): The aiohttp application object.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        """
        Initialize the HealthCheck service with the given DatabaseManager.

        Args:
            db_manager (DatabaseManager): Instance managing DB operations.
        """
        self.db_manager = db_manager
        self.app = web.Application()

        # Prometheus metrics setup
        self.request_counter = Counter(
            "health_requests_total",
            "Total HTTP requests to health endpoints",
            ["endpoint"],
        )
        self.job_count_gauge = Gauge(
            "job_count",
            "Total jobs stored in the database",
        )
        self.memory_usage_gauge = Gauge(
            "memory_usage_mb",
            "Process memory usage in megabytes",
            ["type"],
        )

        self.app.add_routes(
            [
                web.get("/health", self.health_check),
                web.get("/metrics", self.metrics),
            ]
        )

    async def health_check(self, request: web.Request) -> web.Response:
        """
        Basic health check endpoint. Verifies database connectivity and returns a JSON status object.

        Args:
            request (web.Request): Incoming HTTP request (unused).

        Returns:
            web.Response: JSON response containing health status.
        """
        self.request_counter.labels(endpoint="health").inc()
        try:
            if not self.db_manager.is_connected:
                await self.db_manager.initialize()

            job_count = await self.db_manager.get_job_count()
            self.job_count_gauge.set(job_count)
            memory = self._get_memory_usage()
            self.memory_usage_gauge.labels("rss").set(memory["rss_mb"])
            self.memory_usage_gauge.labels("vms").set(memory["vms_mb"])

            data = {
                "status": "healthy",
                "database": "connected",
                "job_count": job_count,
                "timestamp": str(datetime.now()),
            }
            return web.json_response(data)
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return web.json_response(
                {
                    "status": "unhealthy",
                    "error": str(e),
                    "timestamp": str(datetime.now()),
                },
                status=500,
            )

    async def metrics(self, request: web.Request) -> web.Response:
        """
        Metrics endpoint to gather and expose custom stats about the scraper (e.g., job counts).

        Args:
            request (web.Request): Incoming HTTP request (unused).

        Returns:
            web.Response: JSON response with metrics data.
        """
        self.request_counter.labels(endpoint="metrics").inc()
        try:
            job_count = await self.db_manager.get_job_count()
            self.job_count_gauge.set(job_count)
            memory = self._get_memory_usage()
            self.memory_usage_gauge.labels("rss").set(memory["rss_mb"])
            self.memory_usage_gauge.labels("vms").set(memory["vms_mb"])

            metrics_output = generate_latest()
            return web.Response(body=metrics_output, content_type=CONTENT_TYPE_LATEST)
        except Exception as e:
            logger.error(f"Metrics endpoint failed: {str(e)}")
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    def _get_memory_usage(self) -> dict:
        """
        Gather memory usage stats for the current process.

        Returns:
            dict: Dictionary of RSS and VMS usage in MB.
        """
        process = psutil.Process(os.getpid())
        return {
            "rss_mb": process.memory_info().rss / (1024 * 1024),
            "vms_mb": process.memory_info().vms / (1024 * 1024),
        }

    async def start(
        self, host: str = "0.0.0.0", port: int = 8080
    ) -> Tuple[web.AppRunner, web.TCPSite]:
        """
        Start the aiohttp server for health checks and metrics.

        Args:
            host (str): Host interface.
            port (int): Port to listen on.

        Returns:
            Tuple[web.AppRunner, web.TCPSite]: references to the created runner and site.
        """
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Health check server started on http://{host}:{port}")
        return runner, site
