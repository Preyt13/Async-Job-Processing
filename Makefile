.PHONY: up down status test

up:
	./scripts/dev_up.sh

down:
	./scripts/dev_down.sh

status:
	./scripts/dev_status.sh

test:
	cp -n .env.example .env || true
	. .venv/bin/activate && pytest -q
