SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: help secrets up down logs ps approve test lint install

help:
	@echo "secret-broker targets:"
	@echo "  make install   - install dev dependencies (pytest etc.)"
	@echo "  make secrets   - generate throwaway broker/admin tokens in ./secrets (git-ignored)"
	@echo "  make up        - build and start the broker (127.0.0.1 only)"
	@echo "  make down      - stop the broker"
	@echo "  make logs      - follow broker logs"
	@echo "  make approve   - run the approval CLI, e.g. 'make approve list' or 'make approve approve <id>'"
	@echo "  make test      - run the pytest suite"
	@echo "  make lint      - run pre-commit (gitleaks + hygiene)"

secrets:
	@mkdir -p secrets
	@test -s secrets/broker_token || python -c "import secrets;open('secrets/broker_token','w').write(secrets.token_urlsafe(32))"
	@test -s secrets/admin_token  || python -c "import secrets;open('secrets/admin_token','w').write(secrets.token_urlsafe(32))"
	@test -s secrets/openai_api_key || printf 'sk-REPLACE-ME' > secrets/openai_api_key
	@echo "Throwaway tokens written to ./secrets (git-ignored)."
	@echo "Replace ./secrets/openai_api_key with your real key, or inject via op/doppler."

up: secrets
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f broker

ps:
	$(COMPOSE) ps

# Usage: make approve list | make approve show <id> | make approve approve <id> | make approve deny <id>
approve:
	python -m broker.cli.approve $(filter-out $@,$(MAKECMDGOALS))

test:
	python -m pytest -q

lint:
	pre-commit run --all-files

install:
	python -m pip install -r requirements-dev.txt

# Swallow extra goals passed to `make approve ...` so Make does not error on them.
%:
	@:
