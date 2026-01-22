SHELL := /bin/bash

COMPOSE_MINIO := -f infra/compose/iteration-1-minio.compose.yml
COMPOSE_PRODUCER := -f infra/compose/iteration-1-producer.compose.yml

.PHONY: help i1-up i1-run i1-down i1-logs i1-ps i1-clean

help:
	@echo "Targets:"
	@echo "  i1-up     - start MinIO (and init bucket) in background"
	@echo "  i1-run    - run producer job (PUT/GET/DELETE demo)"
	@echo "  i1-logs   - tail MinIO logs"
	@echo "  i1-ps     - show compose containers status"
	@echo "  i1-down   - stop MinIO stack (keeps volumes)"
	@echo ""
	@echo "Examples:"
	@echo "  make i1-up"
	@echo "  make i1-run MSG_SIZE=1MB COUNT=20 VERIFY=1"
	@echo "  make i1-run MSG_SIZE=5MB COUNT=50 VERIFY=1 DELETE=1"
	@echo "  make i1-down"

i1-up:
	docker compose $(COMPOSE_MINIO) up -d

# Parameters:
#   MSG_SIZE (default 1MB)
#   COUNT    (default 20)
#   VERIFY   (set to 1 to enable --verify)
#   DELETE   (set to 1 to enable --delete)
i1-run:
	MSG_SIZE=$${MSG_SIZE:-1MB}; \
	COUNT=$${COUNT:-20}; \
	VERIFY_FLAG=$$( [ "$${VERIFY:-0}" = "1" ] && echo "--verify" || true ); \
	DELETE_FLAG=$$( [ "$${DELETE:-0}" = "1" ] && echo "--delete" || true ); \
	docker compose $(COMPOSE_MINIO) $(COMPOSE_PRODUCER) run --rm producer \
		--msg-size "$$MSG_SIZE" --count "$$COUNT" $$VERIFY_FLAG $$DELETE_FLAG

i1-logs:
	docker compose $(COMPOSE_MINIO) logs -f minio

i1-ps:
	docker compose $(COMPOSE_MINIO) ps

# Stop services but keep volumes (data remains)
i1-down:
	docker compose $(COMPOSE_MINIO) down

i1-clean:
	docker compose $(COMPOSE_MINIO) down -v --remove-orphans
