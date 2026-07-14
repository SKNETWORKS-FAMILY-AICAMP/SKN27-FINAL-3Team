# Road Environment MCP

Road Environment MCP는 사고 지점의 도로환경을 조회하고 분석하기 위해 계획된 MCP 서버입니다.

V1의 개발 방향은 다음과 같습니다.

1. 대한민국 OSM 도로 데이터와 공공데이터 4종을 별도의 Road PostGIS 데이터베이스에 적재합니다.
2. 요청 시 VWorld 검색을 통해 사용자가 입력한 사고 위치 텍스트를 주소·좌표로 확인합니다.
3. 확인된 좌표 주변의 도로환경 데이터를 Road PostGIS에서 조회합니다.
4. 고정된 `road_environment_output_v1` JSON 응답을 Supervisor에 반환합니다.

구조를 변경하기 전에는 `md/` 폴더의 계획 문서를 먼저 확인하세요.

## 로컬 개발 환경 설정

```powershell
cd C:\dev\project\SKN27-FINAL-3Team\road-mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

실제 VWorld 검색이 필요한 경우 `.env` 파일에 `VWORLD_API_KEY` 값을 입력하세요.

## MCP 서버 실행

초기 STDIO 개발 환경:

```powershell
python -m app.server
```

Docker/PostGIS 개발 환경:

```powershell
docker compose -f docker-compose.road.yml up --build
```

HTTP MCP 엔드포인트는 다음 주소로 구성할 예정입니다.

```text
http://localhost:8001/mcp
```

## 폴더별 역할

```text
app/       MCP 서버 및 도로환경 분석 코드
loaders/   OSM 및 공공데이터 적재 스크립트
database/  PostGIS 스키마 및 인덱스
data/      로컬 원본·스냅샷·오류 데이터
tests/     기본 테스트 코드
md/        계획 문서
```