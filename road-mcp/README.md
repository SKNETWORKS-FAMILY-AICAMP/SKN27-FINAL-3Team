# Road Environment MCP

Road Environment MCP is a planned MCP server for accident-location road environment lookup and analysis.

The V1 direction is:

1. Load South Korea OSM road data and four public datasets into a separate Road PostGIS database.
2. Resolve accident location text with VWorld search at request time.
3. Query Road PostGIS around the resolved coordinate.
4. Return a fixed `road_environment_output_v1` JSON response to Supervisor.

See the planning documents in `md/` before changing the structure.

## Local Setup

```powershell
cd C:\dev\project\SKN27-FINAL-3Team\road-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Fill `VWORLD_API_KEY` in `.env` when real VWorld search is needed.

## Run MCP Server

Initial STDIO development:

```powershell
python -m app.server
```

Docker/PostGIS development:

```powershell
docker compose -f docker-compose.road.yml up --build
```

The HTTP MCP endpoint is planned as:

```text
http://localhost:8001/mcp
```

## Folder Roles

```text
app/       MCP server and road analysis code
loaders/   OSM/public-data load scripts
database/  PostGIS schema and indexes
data/      local raw/snapshot/rejected data
tests/     basic tests
md/        planning documents
```
