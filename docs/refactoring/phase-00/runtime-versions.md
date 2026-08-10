# Phase 0 Runtime Versions

- 기준 SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- 작성 기준일: 2026-08-08

| 항목 | 실제 버전 또는 image | 근거 |
|---|---|---|
| Python runtime | 3.13 | `Dockerfile` `FROM python:3.13-slim` |
| CI Python | 3.13 | `.github/workflows/production-gate.yml` |
| Django | 6.0.6 | `requirements.txt` |
| pytest | 9.1.1 | `requirements-dev.txt` |
| pytest-timeout | 2.4.0 | `requirements-dev.txt` |
| Gunicorn | `>=23,<24` | `requirements.txt` |
| Redis client | 8.0.1 | `requirements.txt` |
| psycopg | `>=3.2,<4` | `requirements.txt`, `requirements-dev.txt` |
| pgvector Python package | `>=0.3,<1` | `requirements.txt` |
| CI Node | 24 | `.github/workflows/production-gate.yml` |
| frontend Compose Node | `node:22-alpine` | `docker-compose.yml` |
| React | `^19.0.0` | `app/web/package.json` |
| Vite | `^7.0.0` | `app/web/package.json` |
| PostgreSQL/vector image | `pgvector/pgvector:pg16` | `docker-compose.yml` |
| Redis image | `redis:7-alpine` | `docker-compose.yml` |
| Neo4j image | `neo4j:5-community` | `docker-compose.yml` |
| ClamAV image | `clamav/clamav:stable` | `docker-compose.yml` |
| Terraform CI | 1.15.8 | `.github/workflows/production-gate.yml` |

`app/web/package-lock.json`은 lockfile이고, 이 문서는 package metadata의 declared range를 dependency resolution version으로 확대 해석하지 않는다.
