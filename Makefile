SHELL := /bin/bash

# Compose bundles for the CURRENT iteration
COMPOSE_MINIO := -f infra/compose/iteration-1-minio.compose.yml
COMPOSE_RMQ   := -f infra/compose/iteration-2-rmq.compose.yml
COMPOSE_APP   := -f infra/compose/iteration-2-clients.compose.yml

COMPOSE := docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) $(COMPOSE_APP)

.PHONY: help up ps logs down clean producer consumer
.PHONY: coordinator build

help:
	@echo "Targets (Iteration 2):"
	@echo "  up        - start infra (MinIO + RabbitMQ) in background"
	@echo "  producer  - run producer job (uploads to MinIO, publishes pointers to RMQ)"
	@echo "  consumer  - run branch consumer (consumes pointers, downloads from MinIO)"
	@echo "  ps        - show containers status"
	@echo "  logs      - follow infra logs"
	@echo "  down      - stop infra (keeps volumes)"
	@echo "  clean     - stop + remove volumes + remove orphans"
	@echo ""
	@echo "Examples:"
	@echo "  make up"
	@echo "  make consumer"
	@echo "  make producer MSG_SIZE=1MB COUNT=10 VERIFY=1"
	@echo "  make producer MSG_SIZE=5MB COUNT=50 VERIFY=1 DELETE=1"
	@echo "  make logs"
	@echo "  make clean"

# Start infrastructure only (MinIO + RabbitMQ).
# Clients are run as one-shot jobs via `make producer` / `make consumer`.
up:
	docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) up -d --remove-orphans

ps:
	docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) ps

logs:
	docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) logs -f

down:
	docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) down

clean:
	docker compose $(COMPOSE_MINIO) $(COMPOSE_RMQ) down -v --remove-orphans

# Build all services.
build:
	$(COMPOSE) build

# Run producer as a one-shot job.
# Params:
#   MSG_SIZE (default 1MB)
#   COUNT    (default 5)
#   VERIFY   (set to 1 to enable --verify)
#   DELETE   (set to 1 to enable --delete)
producer:
	MSG_SIZE=$${MSG_SIZE:-1MB}; \
	COUNT=$${COUNT:-5}; \
	VERIFY_FLAG=$$( [ "$${VERIFY:-0}" = "1" ] && echo "--verify" || true ); \
	DELETE_FLAG=$$( [ "$${DELETE:-0}" = "1" ] && echo "--delete" || true ); \
	$(COMPOSE) run --rm producer \
		--msg-size "$$MSG_SIZE" --count "$$COUNT" $$VERIFY_FLAG $$DELETE_FLAG

# Run branch consumer as a long-running job (Ctrl+C to stop).
consumer:
	$(COMPOSE) run --rm branch_consumer

# Run coordinator as a long-running job (Ctrl+C to stop).
coordinator:
	$(COMPOSE) run --rm coordinator
