.PHONY: build up down logs shell dev install lint

build:
	@chmod +x $(PWD)/docker_config/docker-credential-null-creds
	PATH=$(PWD)/docker_config:$$PATH DOCKER_BUILDKIT=0 DOCKER_CONFIG=$(PWD)/docker_config docker compose build --build-arg CACHE_BUST=$(shell git rev-parse HEAD)

up:
	@mkdir -p data
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — fill in your tokens!")
	@chmod +x $(PWD)/docker_config/docker-credential-null-creds
	PATH=$(PWD)/docker_config:$$PATH DOCKER_BUILDKIT=0 DOCKER_CONFIG=$(PWD)/docker_config docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

shell:
	docker compose exec bot bash

dev:
	@mkdir -p data
	uv run dog-weather

install:
	uv sync
