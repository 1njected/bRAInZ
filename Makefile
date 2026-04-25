-include .env
export

.PHONY: up down build restart logs test sync deploy

up:
	docker compose up

down:
	docker compose down

build:
	docker compose up --build

restart:
	docker compose restart brainz

logs:
	docker compose logs -f brainz

test:
	cd tests && docker compose run --rm brainz pytest $(filter-out $@,$(MAKECMDGOALS))

deploy:
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_PATH) && git pull && docker compose restart brainz"
