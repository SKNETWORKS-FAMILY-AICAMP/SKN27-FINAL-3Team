# Road Environment MCP 폴더 구조 계획

> 작성일: 2026-07-14  
> 기준 문서: `road_environment_mcp_V1 계획.md`  
> 목적: V1 구현자가 이해하기 쉬운 Road Environment MCP 폴더 구조를 정한다.  
> 결론: 처음부터 너무 세분화하지 않고, 데이터 로드·DB·MCP 서버·테스트만 명확히 나눈다.

---

# 1. 재검토 결론

처음 제안한 구조는 장기 운영까지 생각하면 틀린 방향은 아니지만, V1 구현 시작 구조로는 복잡하다.

특히 다음 폴더명은 처음 보는 사람이 바로 이해하기 어렵다.

```text
etl
repositories
analyzers
builders
contract
```

따라서 V1에서는 아래처럼 단순하게 간다.

```text
road-mcp/
├─ md/              문서
├─ app/             MCP 서버 코드
├─ loaders/         데이터를 가져와 DB에 넣는 코드
├─ database/        PostGIS 테이블 생성 SQL
├─ data/            내려받은 원본 데이터 보관
├─ tests/           테스트
├─ docker-compose.road.yml
├─ Dockerfile
├─ .env.example
└─ README.md
```

이 구조가 더 좋은 이유:

```text
app
→ 실제 MCP 서버가 있는 곳

loaders
→ OSM PBF와 공공데이터를 로드하는 곳

database
→ DB 테이블과 인덱스를 만드는 곳

data
→ 다운로드한 원본 파일과 실패 데이터를 보관하는 곳

tests
→ 제대로 되는지 확인하는 곳
```

---

# 2. 최종 권장 폴더 구조

```text
road-mcp/
├─ README.md
├─ .env.example
├─ pyproject.toml
├─ Dockerfile
├─ docker-compose.road.yml
├─ md/
│  ├─ gateway_swagger_guide.pdf
│  ├─ road_environment_mcp_V1 계획.md
│  ├─ road_environment_mcp_폴더구조_계획.md
│  └─ road_environment_mcp_데이터로드_검증계획.md
├─ app/
│  ├─ __init__.py
│  ├─ server.py
│  ├─ config.py
│  ├─ schemas.py
│  ├─ road_tool.py
│  ├─ vworld_client.py
│  ├─ db.py
│  ├─ road_query.py
│  ├─ road_analysis.py
│  └─ response_builder.py
├─ loaders/
│  ├─ README.md
│  ├─ common.py
│  ├─ load_osm.py
│  ├─ osm2pgsql_flex.lua
│  ├─ load_road_signs.py
│  ├─ load_traffic_signals.py
│  ├─ load_crosswalks.py
│  ├─ load_protection_zones.py
│  └─ validate_loaded_data.py
├─ database/
│  ├─ 001_init_postgis.sql
│  ├─ 002_create_tables.sql
│  ├─ 003_create_indexes.sql
│  └─ 004_create_sync_logs.sql
├─ data/
│  ├─ raw/
│  ├─ snapshots/
│  └─ rejected/
└─ tests/
   ├─ test_schema.py
   ├─ test_vworld_client.py
   ├─ test_road_query.py
   ├─ test_road_analysis.py
   ├─ test_loaders.py
   └─ test_mcp_tool.py
```

---

# 3. 각 폴더 설명

## 3.1 `md`

계획서와 설명 문서를 둔다.

```text
md/
├─ road_environment_mcp_V1 계획.md
├─ road_environment_mcp_폴더구조_계획.md
└─ road_environment_mcp_데이터로드_검증계획.md
```

## 3.2 `app`

Road Environment MCP 서버의 실제 코드가 들어간다.

```text
app/
├─ server.py
├─ config.py
├─ schemas.py
├─ road_tool.py
├─ vworld_client.py
├─ db.py
├─ road_query.py
├─ road_analysis.py
└─ response_builder.py
```

파일별 역할:

| 파일 | 역할 |
|---|---|
| `server.py` | MCP 서버 실행 시작점 |
| `config.py` | 환경변수 로드 |
| `schemas.py` | MCP 입력·출력 구조 검증 |
| `road_tool.py` | `inspect_road_environment` MCP 도구 |
| `vworld_client.py` | VWorld 검색 API 호출 |
| `db.py` | PostGIS 연결 |
| `road_query.py` | PostGIS에서 주변 도로·시설 조회 |
| `road_analysis.py` | 기준도로, 교차로, 램프, 보호구역 분석 |
| `response_builder.py` | 최종 JSON 응답 생성 |

처음에는 이 정도로 충분하다. 나중에 `road_analysis.py`가 너무 커지면 그때 `analysis/` 폴더로 나누면 된다.

---

# 4. `loaders` 폴더 설명

`loaders`는 데이터를 가져와서 Road PostGIS에 넣는 코드다.

처음 제안했던 `etl`이라는 이름은 개발자에게는 익숙하지만, 팀원이 보기에는 추상적일 수 있다. 그래서 V1에서는 `loaders`가 더 직관적이다.

```text
loaders/
├─ README.md
├─ common.py
├─ load_osm.py
├─ osm2pgsql_flex.lua
├─ load_road_signs.py
├─ load_traffic_signals.py
├─ load_crosswalks.py
├─ load_protection_zones.py
└─ validate_loaded_data.py
```

파일별 역할:

| 파일 | 역할 |
|---|---|
| `common.py` | 공통 DB 연결, 로그, 좌표 처리 |
| `load_osm.py` | 대한민국 OSM PBF 다운로드와 적재 실행 |
| `osm2pgsql_flex.lua` | osm2pgsql로 도로 데이터만 추출하는 설정 |
| `load_road_signs.py` | 도로안내표지 데이터 적재 |
| `load_traffic_signals.py` | 신호등 데이터 적재 |
| `load_crosswalks.py` | 횡단보도 데이터 적재 |
| `load_protection_zones.py` | 보호구역 데이터 적재 |
| `validate_loaded_data.py` | 적재 후 건수·좌표·geometry 검증 |

`loaders`는 운영 서비스 코드가 아니라 배치성 작업 코드다.

---

# 5. `database` 폴더 설명

PostGIS 테이블을 만드는 SQL 파일을 둔다.

```text
database/
├─ 001_init_postgis.sql
├─ 002_create_tables.sql
├─ 003_create_indexes.sql
└─ 004_create_sync_logs.sql
```

파일별 역할:

| 파일 | 역할 |
|---|---|
| `001_init_postgis.sql` | PostGIS 확장 활성화 |
| `002_create_tables.sql` | OSM 도로, 신호등, 횡단보도, 보호구역 테이블 생성 |
| `003_create_indexes.sql` | 공간 인덱스 생성 |
| `004_create_sync_logs.sql` | 데이터 적재 이력 테이블 생성 |

처음부터 `migrations`, `schema`, `sql`로 나누지 않는다. SQL 파일이 많아졌을 때만 나눈다.

---

# 6. `data` 폴더 설명

다운로드한 원본 데이터와 실패 데이터를 보관한다.

```text
data/
├─ raw/
│  ├─ osm/
│  ├─ api_samples/
│  └─ reference/
├─ snapshots/
│  ├─ road_signs_YYMMDD/
│  ├─ traffic_signals_YYMMDD/
│  ├─ crosswalks_YYMMDD/
│  └─ protection_zones_YYMMDD/
│     └─ {sggCd}/
└─ rejected/
   └─ protection_zones/
```

| 폴더 | 역할 |
|---|---|
| `raw/osm` | Geofabrik OSM PBF 파일 보관. 파일명은 redirect 최종 파일명 사용 |
| `raw/api_samples` | API 1건 미리보기 응답 |
| `raw/reference` | 시군구 코드 등 참조 CSV |
| `snapshots` | 공공데이터 원본 JSON 수집본. 폴더명은 `source_YYMMDD` |
| `rejected/protection_zones` | 보호구역 실패 sggCd 재시도 큐 |

주의:

```text
data/raw
data/snapshots
data/rejected
```

이 폴더에는 큰 파일이 들어갈 수 있으므로 `.gitignore`에 넣는 것이 좋다. 문서와 샘플만 Git에 올린다.

현재 예시:

```text
data/raw/osm/south-korea-260713.osm.pbf
data/snapshots/road_signs_260714/page_00001.json
data/snapshots/traffic_signals_260714/page_00001.json
data/snapshots/crosswalks_260714/page_00001.json
data/snapshots/protection_zones_260714/11110/page_00001.json
data/rejected/protection_zones/29110_error.json
```

---

# 7. `tests` 폴더 설명

처음에는 테스트 폴더도 단순하게 둔다.

```text
tests/
├─ test_schema.py
├─ test_vworld_client.py
├─ test_road_query.py
├─ test_road_analysis.py
├─ test_loaders.py
└─ test_mcp_tool.py
```

나중에 테스트가 많아지면 그때 아래처럼 나눈다.

```text
tests/
├─ unit/
├─ integration/
└─ fixtures/
```

V1 시작부터 `unit`, `integration`, `contract`를 나누면 오히려 어디에 테스트를 넣어야 할지 헷갈릴 수 있다.

---

# 8. 실행 방식

## 8.1 초기 개발

초기에는 STDIO 방식으로 MCP 자체 기능을 확인할 수 있다.

```text
command: python
args:
  - -m
  - app.server
cwd: C:\dev\project\SKN27-FINAL-3Team\road-mcp
```

## 8.2 Docker 통합 후

Supervisor 연동까지 생각하면 최종 형태는 Streamable HTTP가 더 적합하다.

```text
Supervisor
→ road-mcp:8001
→ road-postgis:5432
```

Codex MCP 등록 화면에는 MCP 서버가 실제로 완성된 뒤 아래처럼 등록한다.

```text
이름: road-environment-mcp
유형: Streamable HTTP
URL: http://localhost:8001/mcp
```

지금 MCP 등록 화면에 임의 값을 넣어도 Road MCP가 만들어지지는 않는다.

---

# 9. 환경변수

`.env.example`에는 실제 비밀번호나 API 키를 넣지 않는다.

```text
VWORLD_API_KEY=
ROAD_DB_HOST=road-postgis
ROAD_DB_PORT=5432
ROAD_DB_NAME=road_environment
ROAD_DB_USER=road_user
ROAD_DB_PASSWORD=
ROAD_MCP_HOST=0.0.0.0
ROAD_MCP_PORT=8001
```

---

# 10. 처음 만들 파일 목록

1차 구현에서는 아래 파일만 먼저 만든다.

```text
road-mcp/README.md
road-mcp/.env.example
road-mcp/pyproject.toml
road-mcp/Dockerfile
road-mcp/docker-compose.road.yml
road-mcp/app/__init__.py
road-mcp/app/server.py
road-mcp/app/config.py
road-mcp/app/schemas.py
road-mcp/app/road_tool.py
road-mcp/app/vworld_client.py
road-mcp/app/db.py
road-mcp/app/road_query.py
road-mcp/app/road_analysis.py
road-mcp/app/response_builder.py
road-mcp/loaders/README.md
road-mcp/loaders/common.py
road-mcp/loaders/load_osm.py
road-mcp/loaders/osm2pgsql_flex.lua
road-mcp/loaders/load_road_signs.py
road-mcp/loaders/load_traffic_signals.py
road-mcp/loaders/load_crosswalks.py
road-mcp/loaders/load_protection_zones.py
road-mcp/loaders/validate_loaded_data.py
road-mcp/database/001_init_postgis.sql
road-mcp/database/002_create_tables.sql
road-mcp/database/003_create_indexes.sql
road-mcp/database/004_create_sync_logs.sql
road-mcp/tests/test_schema.py
road-mcp/tests/test_mcp_tool.py
```

---

# 11. 나중에 커지면 나눌 구조

처음부터 아래처럼 만들 필요는 없다.

다만 파일이 커지면 이 방향으로 분리한다.

```text
app/road_analysis.py
→ app/analysis/
   ├─ road_matcher.py
   ├─ intersection.py
   └─ ramp.py

app/road_query.py
→ app/queries/
   ├─ osm_roads.py
   ├─ traffic_facilities.py
   └─ protection_zones.py

tests/
→ tests/unit/
→ tests/integration/
```

즉, V1 시작 구조는 단순하게 두고, 실제로 복잡해지는 파일만 나중에 쪼갠다.

---

# 12. 최종 결정

V1에서는 다음 구조를 채택한다.

```text
road-mcp/
├─ md/
├─ app/
├─ loaders/
├─ database/
├─ data/
└─ tests/
```

이 구조가 현재 프로젝트에 가장 적합하다.

이유:

```text
1. 폴더 이름만 봐도 역할이 보인다.
2. 구현 초기에 파일 위치를 고민할 일이 적다.
3. 데이터 로드 코드와 MCP 서버 코드가 섞이지 않는다.
4. PostGIS SQL이 한곳에 모인다.
5. 나중에 커질 때 자연스럽게 세분화할 수 있다.
```
