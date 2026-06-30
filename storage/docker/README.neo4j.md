# Neo4j local setup

Neo4j is used for two graph layers:

- `Hint Graph`: user terms -> legal terms -> violation/penalty types -> search terms
- `Law Graph`: law source -> version -> chunk and provision relationships

It is not the vector store. Semantic chunk search stays in `pgvector` or the
embedding artifact layer.

## Start Neo4j

Copy `.env.example` to `.env` and set `NEO4J_PASSWORD`.

```powershell
docker compose --env-file .env -f storage/docker/docker-compose.neo4j.yml up -d
```

Browser:

```text
http://localhost:7474
```

Bolt URI:

```text
bolt://localhost:7687
```

## Load legal artifacts and hint graph

```powershell
python -m etl.legal.export_neo4j `
  --output-dir output/law_ingestion `
  --hint-terms storage/rag/law_query_terms.yaml
```

The loader reads these files:

```text
output/law_ingestion/normalized/legal_sources.jsonl
output/law_ingestion/normalized/legal_source_versions.jsonl
output/law_ingestion/chunks/law_chunks.jsonl
output/law_ingestion/relations/law_relations.jsonl
storage/rag/law_query_terms.yaml
```

## Quick checks

```cypher
MATCH (n:UserTerm)-[:NORMALIZES_TO]->(t:LegalTerm)
RETURN n.text, t.text
LIMIT 20;
```

```cypher
MATCH (s:LegalSource)-[:HAS_VERSION]->(v:LawVersion)-[:HAS_CHUNK]->(c:LawChunk)
RETURN s.source_name, v.enforce_date, c.article_no, c.chunk_type
LIMIT 20;
```
