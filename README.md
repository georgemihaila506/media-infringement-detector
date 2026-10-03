# Media infringement detector

Detects republished photos and videos from a rights catalog. The design and the 14-week plan are in [infringement-detection-plan.md](infringement-detection-plan.md). What to build next, and what each step teaches, is in [ROADMAP.md](ROADMAP.md).

## Layout

```
src/infringement/     the shipped package (EC2 and the Lambda image)
    common/           settings and AWS client factories
    matcher/          fingerprinting and verification; pure, no network I/O
    engine/           durable execution engine: replay, storage, workers, timers, transport
    workflows/        ingest_original and scan_suspect
    activities/       activity implementations, Lambda handler, local runner
    app/              FastAPI API and HTMX review UI
infra/                Terraform
eval/                 attack generator, evaluation harness, results
loadtest/             Locust scenarios, chaos scripts, reports
db/migrations         SQL run by Postgres on first start
tests/
```

## Getting started

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/) and Docker; Terraform for the AWS deployment.

```sh
cp .env.example .env
just sync      # install dependencies
just up        # Postgres + pgvector, SeaweedFS (S3), ElasticMQ (SQS)
just test
```

ElasticMQ has a queue UI at http://localhost:9325.
