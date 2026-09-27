set dotenv-load

default:
    @just --list

# Install all dependencies into .venv
sync:
    uv sync --all-extras

# Start the local stack (Postgres + pgvector, SeaweedFS (S3), ElasticMQ (SQS))
up:
    docker compose up -d

down:
    docker compose down

# Wipe local data volumes (re-runs migrations on next `up`)
reset:
    docker compose down -v

psql:
    docker compose exec postgres psql -U infringement

test:
    uv run pytest

lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Regenerate the labeled attack dataset, deterministically
dataset:
    uv run python -m eval.attacks

# Run the evaluation harness and write results to eval/results/
eval:
    uv run python -m eval.harness

# Local stand-in for Lambda: polls ElasticMQ and runs activities
runner:
    uv run python -m infringement.activities.runner

worker:
    uv run python -m infringement.engine.worker

api:
    uv run uvicorn infringement.app.main:app --reload

tf-init:
    terraform -chdir=infra init

plan:
    terraform -chdir=infra plan

deploy:
    terraform -chdir=infra apply

destroy:
    terraform -chdir=infra destroy
