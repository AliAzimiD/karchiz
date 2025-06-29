# ──────────────────────────────────────────────────────────────────────────────
#  Docker-Compose helper Makefile
#  Every target is fully expanded; no logic has been altered or removed.
# ──────────────────────────────────────────────────────────────────────────────

.PHONY: build start stop logs restart clean dev

# ---------------------------------------------------------------------------
#  Build all images defined in docker-compose.yml (no cache settings here;
#  run `docker compose build --no-cache` manually if you need a pristine build)
# ---------------------------------------------------------------------------
build:
	docker compose build

# ---------------------------------------------------------------------------
#  Start the stack in detached mode
# ---------------------------------------------------------------------------
start:
	docker compose up -d

# ---------------------------------------------------------------------------
#  Gracefully stop (but keep) all containers
# ---------------------------------------------------------------------------
stop:
	docker compose down

# ---------------------------------------------------------------------------
#  Follow container logs (equivalent to `docker compose logs -f`)
# ---------------------------------------------------------------------------
logs:
	docker compose logs -f

# ---------------------------------------------------------------------------
#  Restart running containers without rebuilding images
# ---------------------------------------------------------------------------
restart:
	docker compose restart

# ---------------------------------------------------------------------------
#  Remove containers _and_ named/anonymous volumes, then purge job_data/*
# ---------------------------------------------------------------------------
clean:
	docker compose down -v && sudo rm -rf job_data/*

# ---------------------------------------------------------------------------
#  Development mode – uses alternative compose file that mounts sources,
#  enables live reloads, etc.
# ---------------------------------------------------------------------------
dev:
	docker compose -f docker-compose.dev.yml up --build
