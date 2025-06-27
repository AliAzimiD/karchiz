# Makefile

.PHONY: build start stop logs restart clean dev

build:
        docker compose build

start:
        docker compose up -d

stop:
        docker compose down

logs:
        docker compose logs -f

restart:
        docker compose restart

clean:
        docker compose down -v
	sudo rm -rf job_data/*

dev:
        docker compose -f docker-compose.dev.yml up --build
