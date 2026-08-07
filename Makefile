# None of these produces a file of its own name, and without .PHONY `make` would treat a
# `secrets/`, `gates/` or `e2e/` appearing in the tree as "already built" and skip the
# commands silently. A check that silently does not run is the failure mode this file is
# being changed to prevent, so the new targets go here too.
.PHONY: up down logs setup-secret test e2e lint typecheck gates secrets check

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

# Local dev checks.
#
# `check` used to run lint + typecheck + test and claim to "mirror the CI code job", which
# left three of CI's five required contexts unrepresented: the whole `gates` job
# (check_stories, check_digest_confinement), the e2e lane, and `secrets`. A local green that
# proves less than it says is worse than no local gate, because it is the one people trust
# before pushing.
test:
	uv run pytest

# The browser lane. Deselected from `test` by `addopts = -m 'not e2e'`, so a plain run
# reports "N passed, 8 deselected" and reads as green while the only tests that drive a real
# browser were never run. Needs `uv run playwright install --with-deps webkit chromium` once.
e2e:
	uv run pytest -m e2e

lint:
# `scripts` as well as `src`. FOUR of this repo's gates live there — check_stories,
# check_digest_confinement, check_compose_overlay and check_signoff — and nothing linted
# them, so nine findings sat in code whose whole job is to be trusted. Found while cutting
# a tag, by running ruff over both directories on the tree about to be tagged.
	uv run ruff check src scripts
	uv run ruff format --check src scripts

typecheck:
	uv run mypy src

# The CI `gates` job, which `check` did not run at all.
gates:
	uv run --with pyyaml python scripts/check_stories.py
	uv run --with pyyaml python scripts/check_compose_overlay.py
	uv run python scripts/check_digest_confinement.py
# The DCO check, pointed at origin/main so it has something to compare against locally.
# Without BASE_SHA it correctly reports "not a pull request" and passes — which is right in
# CI on a push, and useless here, where the whole point is to see the answer before pushing.
	BASE_SHA=origin/main uv run python scripts/check_signoff.py

# The CI `secrets` job, run the way CI runs it: the WHOLE commit graph, with this repo's
# config passed explicitly.
#
# `git` mode, not `dir`, and that is the point. CI checks out with `fetch-depth: 0`, which
# fetches EVERY branch, so `gitleaks git .` scans every commit anyone has pushed — one
# credential-shaped literal on a single unmerged branch fails `secrets` on every open PR at
# once, including PRs that did not change. That happened: 171 commits scanned, one finding,
# on a branch nobody had merged. Run this before you push.
secrets:
	gitleaks git --no-banner --redact -c .gitleaks.toml .

check: lint typecheck gates test secrets
	@echo "check covers CI's code+gates+secrets. Run 'make e2e' for the browser lane."
