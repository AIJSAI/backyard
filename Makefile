.PHONY: up down logs setup-secret test lint typecheck check

# One command for a clean machine: generate .env if missing, then bring the stack up.
up:
	@test -f .env || { \
	  umask 077; \
	  { \
	    printf 'POSTGRES_PASSWORD=%s\n' "$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"; \
	    printf 'POSTGRES_MIGRATOR_PASSWORD=%s\n' "$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"; \
	    printf 'POSTGRES_APP_PASSWORD=%s\n' "$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"; \
	  } > .env; \
	  echo "Generated .env (mode 0600) with random passwords for the three database roles."; \
	}
	docker compose up --build -d
	@echo ""
	@echo "Backyard is starting. Read the one-time setup secret with:  make setup-secret"
	@echo "Then open http://localhost:8000/setup/"

setup-secret:
	@docker compose logs --no-log-prefix web 2>/dev/null | awk '/paste this one-time secret/{getline; gsub(/^ +/,""); print}' | tail -1

down:
	docker compose down

logs:
	docker compose logs -f web

# Local dev checks. These mirror the CI `code` job.
test:
	uv run pytest

lint:
	uv run ruff check src
	uv run ruff format --check src

typecheck:
	uv run mypy src

check: lint typecheck test
