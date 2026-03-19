.PHONY: build up down logs shell dev install lint

build:
	docker compose build

up:
	@mkdir -p data
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — fill in your tokens!")
	@mkdir -p ~/.docker && python3 -c "import json,os; p=os.path.expanduser('~/.docker/config.json'); d=json.load(open(p)) if os.path.exists(p) else {}; d['credsStore']=''; json.dump(d,open(p,'w'),indent=2)"
	docker compose up -d

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
