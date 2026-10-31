# Thin wrapper over the root package.json scripts (the primary, cross-platform entry point).
.PHONY: install dev db-local migrate lint typecheck test check build knowledge-lock benchmark docker-up docker-down

install:
	pnpm install && pnpm api:install
dev:
	pnpm dev
db-local:
	pnpm db:local
migrate:
	pnpm migrate
lint:
	pnpm lint
typecheck:
	pnpm typecheck
test:
	pnpm test
check:
	pnpm check
build:
	pnpm build:web
knowledge-lock:
	pnpm knowledge:lock
benchmark:
	pnpm benchmark
docker-up:
	pnpm docker:up
docker-down:
	pnpm docker:down
