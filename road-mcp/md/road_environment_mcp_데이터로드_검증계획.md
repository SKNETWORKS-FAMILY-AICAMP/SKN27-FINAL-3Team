# Road Environment MCP 데이터 로드 및 검증 계획

> 작성일: 2026-07-14  
> 기준 문서: `road_environment_mcp_V1 계획.md`  
> 목적: Road Environment MCP가 사용할 전국 도로환경 데이터를 어떻게 적재하고, 어떻게 검증할지 정리한다.

---

# 1. 핵심 원칙

운영 중 사용자 상담 요청마다 공공데이터 API나 Overpass API를 반복 호출하지 않는다. 분석에 필요한 전국 데이터는 사전에 Road PostGIS에 적재하고, 실시간 요청에서는 내부 DB를 조회한다.

```text
사전 적재
→ 대한민국 OSM PBF
→ 공공데이터 4종
→ Road PostGIS

실시간 요청
→ VWorld 위치 검색
→ 단일 후보면 PostGIS 조회
→ 다중 후보면 Supervisor 재질문
→ 선택 좌표로 MCP 재호출
```

VWorld 검색 API는 위치 후보를 찾기 위한 실시간 서비스다. 전국 주소 DB를 만들기 위한 적재 대상이 아니다.

---

# 2. 데이터 원천

| 구분 | 원천 | 사용 방식 | 역할 |
|---|---|---|---|
| 도로 구조 | 대한민국 OSM PBF | 사전 적재 | 도로 geometry, 도로종류, 연결관계, 교차로, 램프 분석 |
| 도로안내표지 | 공공데이터 표준데이터 | 사전 적재 | 기준도로, 노선, 방향 안내 보완 |
| 신호등 | 공공데이터 표준데이터 | 사전 적재 | 차량신호등·보행자신호등 여부 보완 |
| 횡단보도 | 공공데이터 표준데이터 | 사전 적재 | 횡단보도, 교통섬, 보행자 시설 보완 |
| 보호구역 | 경찰청 전국 보호구역 현황 | 사전 적재 | 어린이·노인·장애인 보호구역 판정 |
| 위치 검색 | VWorld 검색 API | 실시간 | 사고위치·주소·장소명에서 후보 좌표 확보 |
| 좌표 주소화 | VWorld Geocoder | V2 실시간 | 지도 선택 좌표의 주소 확인 |
| 지도 선택 | VWorld 2D 지도 | V2 실시간 | 사용자가 사고지점을 직접 선택 |
| OSM 확인 | Overpass API | 선택적 확인 | 특정 지점의 OSM 원천 확인. 운영 분석 주 경로는 아님 |

---

# 3. 전체 로드 흐름

```text
1. 원천 데이터 확보
2. 원본 스냅샷 저장
3. 정규화 및 좌표 변환
4. staging 테이블 적재
5. 품질 검증
6. 운영 테이블 교체
7. 적재 이력과 품질 리포트 저장
```

운영 테이블에 직접 적재하지 않는다. 검증 실패 시 기존 운영 테이블을 유지한다.

```text
raw/snapshot
→ staging
→ quality check
→ production swap
```

---

# 4. OSM PBF 로드 계획

## 4.1 수집

대한민국 OSM PBF는 Geofabrik의 South Korea extract를 기준으로 한다.

```text
download.geofabrik.de/asia/south-korea-latest.osm.pbf
```

저장 위치:

```text
road-mcp/data/raw/osm/south-korea-latest.osm.pbf
road-mcp/data/snapshots/osm/YYYYMMDD/south-korea-latest.osm.pbf
```

## 4.2 변환

`osm2pgsql Flex`를 사용해 도로환경 분석에 필요한 객체만 선별한다.

적재 대상:

```text
highway=* 도로 way
도로 geometry 구성에 필요한 node
도로 route relation
turn restriction relation
junction=roundabout
motorway_link·trunk_link·primary_link 등 link 도로
bridge·tunnel·layer 태그
name·ref·lanes·oneway·maxspeed·destination 태그
```

기본적으로 제외할 대상:

```text
건물
상점
공원
관광 POI
도로환경 분석과 무관한 일반 시설
```

## 4.3 staging 적재

권장 staging 테이블:

```text
road_staging.osm_road_ways
road_staging.osm_road_nodes
road_staging.osm_road_relations
road_staging.osm_turn_restrictions
```

주요 컬럼:

```text
osm_way_id
road_name
road_ref
highway_type
lane_count
oneway
junction_type
destination
destination_ref
maxspeed
bridge
tunnel
layer
geom
osm_updated_at
loaded_at
raw_tags
```

## 4.4 운영 반영

검증 성공 후 운영 스키마로 교체한다.

```text
road_staging.osm_road_ways
→ road_prod.osm_road_ways
```

교체 방식은 V1에서는 전체 교체를 기본으로 한다.

```text
새 staging 적재 완료
→ 검증 성공
→ 기존 production 백업 또는 rename
→ staging을 production으로 교체
→ 공간 인덱스 생성 확인
```

향후에는 OSM replication 변경분 적용으로 고도화할 수 있다.

---

# 5. 공공데이터 4종 로드 계획

## 5.1 Swagger 확인 후 URL 확정

공공데이터 4종은 같은 공공데이터포털 계열이라도 API 경로와 필수 파라미터가 다를 수 있다. 따라서 로더 구현 전에 각 데이터셋의 Swagger 화면에서 다음 항목을 먼저 확정한다.

```text
1. Base URL
2. GET 호출 경로
3. 필수 파라미터
4. 선택 파라미터
5. 응답 형식 JSON/XML
6. 응답의 목록 배열 위치
7. 전체 건수 필드명
8. 좌표 또는 geometry 필드명
```

`.env`에는 `serviceKey`, `pageNo`, `numOfRows`를 붙인 전체 URL을 넣지 않는다. URL에는 Base URL과 GET 호출 경로만 넣고, 공통 로더가 `serviceKey`, `pageNo`, `numOfRows`를 요청 파라미터로 붙인다.

예시:

```env
PROTECTION_ZONES_API_URL=https://apis.data.go.kr/1320000/safetyzonedtlinfo/getdtllist
```

잘못된 예시:

```env
PROTECTION_ZONES_API_URL=https://apis.data.go.kr/1320000/safetyzonedtlinfo/getdtllist?serviceKey=...&pageNo=1&numOfRows=100
```

## 5.2 공공데이터 인증키 처리

공공데이터포털 Swagger 화면에서는 `serviceKey`에 일반 인증키, 즉 Decoding 키를 입력한다.

```text
PUBLIC_DATA_API_KEY
→ 공공데이터포털 일반 인증키 Decoding 값
```

Encoding 키를 넣으면 호출 URL에서 다시 인코딩되면서 인증 실패가 날 수 있으므로, V1 로더 기준은 Decoding 키로 통일한다.

## 5.3 원천별 URL 환경변수

```env
ROAD_SIGNS_API_URL=
TRAFFIC_SIGNALS_API_URL=
CROSSWALKS_API_URL=
PROTECTION_ZONES_API_URL=
```

각 값은 Swagger에서 확인한 Base URL과 GET 호출 경로를 합친 값이다.

```text
Base URL: https://apis.data.go.kr/1320000/safetyzonedtlinfo
GET 경로: /getDtlList
최종 URL: https://apis.data.go.kr/1320000/safetyzonedtlinfo/getdtllist
```

## 5.4 원천별 파라미터 차이

공통으로 기대하는 파라미터:

```text
serviceKey
pageNo
numOfRows
```

하지만 모든 API가 이 3개만으로 전국 전체를 반환한다고 가정하면 안 된다.

| 원천 | URL 변수 | 공통 파라미터 | 추가 필수/주의 파라미터 | 적재 방식 |
|---|---|---|---|---|
| 도로안내표지 | `ROAD_SIGNS_API_URL` | `serviceKey`, `pageNo`, `numOfRows` | Swagger 확인 후 추가 | 전체 페이지 순회 |
| 신호등 | `TRAFFIC_SIGNALS_API_URL` | `serviceKey`, `pageNo`, `numOfRows` | Swagger 확인 후 추가 | 전체 페이지 순회 |
| 횡단보도 | `CROSSWALKS_API_URL` | `serviceKey`, `pageNo`, `numOfRows` | Swagger 확인 후 추가 | 전체 페이지 순회 |
| 보호구역 | `PROTECTION_ZONES_API_URL` | `serviceKey`, `pageNo`, `numOfRows` | `sggCd` 필수 | 시군구 코드별 페이지 순회 |

## 5.5 보호구역 API 특이사항

`경찰청_전국 보호구역 현황`은 Swagger 화면 기준으로 다음 구조다.

```text
Base URL: https://apis.data.go.kr/1320000/safetyzonedtlinfo
GET 경로: /getDtlList
설명: 보호구역목록조회
```

최종 URL:

```env
PROTECTION_ZONES_API_URL=https://apis.data.go.kr/1320000/safetyzonedtlinfo/getdtllist
```

확인된 파라미터:

| 파라미터 | 필수 | 설명 | 처리 |
|---|---:|---|---|
| `serviceKey` | 필수 | 공공데이터포털 인증키 | `PUBLIC_DATA_API_KEY` 사용 |
| `numOfRows` | 선택/권장 | 한 페이지 결과 수 | `PUBLIC_DATA_DEFAULT_NUM_OF_ROWS` 사용 |
| `pageNo` | 선택/권장 | 페이지 번호 | 로더가 1부터 반복 |
| `callDate` | 선택 | 변경기준일자 | 필요 시 `PROTECTION_ZONE_CALL_DATE` 사용 |
| `assignType` | 선택 | 지정구분. `1`: 우선지정대상, `2`: 지정대상 | 필요 시 `PROTECTION_ZONE_ASSIGN_TYPE` 사용 |
| `sggCd` | 필수 | 시군구코드 | `PROTECTION_ZONE_SGG_CODES`를 반복 |
| `emdongCd` | 선택 | 읍면동코드 | V1에서는 기본 미사용 |
| `rprsPtznMngNo` | 선택 | 대표보호구역관리번호 | 단건 확인용. V1 전국 적재에서는 미사용 |

따라서 보호구역은 다음처럼 호출한다.

```text
시군구코드 목록 준비
→ sggCd=첫 번째 코드, pageNo=1 호출
→ 전체 건수 확인
→ 해당 sggCd의 모든 페이지 수집
→ 다음 sggCd 반복
→ 전체 시군구 완료 후 staging 검증
```

보호구역용 환경변수:

```env
PROTECTION_ZONE_SGG_CODES=11110,11140
PROTECTION_ZONE_ASSIGN_TYPE=
PROTECTION_ZONE_CALL_DATE=
```

V1 초기에는 테스트용으로 시군구 코드 1개만 넣고 호출을 검증한다. 전국 적재 단계에서는 대한민국 전체 시군구 코드 목록을 파일 또는 환경변수로 관리한다.

권장 파일:

```text
road-mcp/data/raw/reference/sgg_codes.csv
```

권장 컬럼:

```text
sgg_cd
sigungu_name
sido_name
enabled
```

전국 적재 시에는 `enabled=true`인 시군구만 반복한다.

## 5.6 공통 수집 방식

각 원천은 페이지네이션을 끝까지 순회한다.

```text
첫 페이지 호출
→ 전체 건수 확인
→ 페이지 반복
→ 원본 응답 저장
→ 레코드 정규화
→ 좌표·geometry 생성
→ staging 적재
→ 품질 검증
→ 운영 반영
```

단, 보호구역은 `sggCd`별로 위 흐름을 반복한다.

```text
보호구역:
시군구 코드 반복
→ 각 시군구별 페이지 반복
→ 전체 결과 병합
→ staging 적재
→ 시군구별 누락 검증
```

## 5.7 공통 컬럼

```text
id
source_id
source_name
road_name
road_address
parcel_address
latitude
longitude
geom
source_reference_date
collected_at
loaded_at
raw_json
```

`raw_json`은 반드시 보존한다.

```text
원천 필드 변경 추적
정규화 오류 추적
분쟁 시 원본 근거 확인
재처리 가능성 확보
```

## 5.8 원천별 운영 테이블

```text
road_prod.road_guide_signs
road_prod.traffic_signals
road_prod.crosswalks
road_prod.protection_zones
```

각 테이블은 동일한 공통 컬럼을 갖되, 원천별 특화 컬럼을 추가한다.

```text
road_guide_signs
→ sign_type, direction_text, route_number

traffic_signals
→ signal_type, control_type, flashing_operation

crosswalks
→ crosswalk_type, pedestrian_signal, traffic_island, raised_crosswalk

protection_zones
→ zone_type, facility_name, zone_radius, polygon_source
```

## 5.9 원천별 응답 구조 확인 체크리스트

로더를 구현하기 전에 각 API를 `numOfRows=1`, `pageNo=1`로 호출해 응답 구조를 저장한다.

저장 위치:

```text
road-mcp/data/raw/api_samples/road_signs_page1.json
road-mcp/data/raw/api_samples/traffic_signals_page1.json
road-mcp/data/raw/api_samples/crosswalks_page1.json
road-mcp/data/raw/api_samples/protection_zones_sggCd_샘플_page1.json
```

확인 항목:

```text
응답 성공 코드 위치
전체 건수 필드명
목록 배열 필드명
페이지 번호 필드명
한 페이지 결과 수 필드명
좌표 필드명
geometry 필드명
주소 필드명
기준일자 필드명
원천 고유 ID 필드명
```

이 확인이 끝나기 전에는 production 적재 로직을 만들지 않는다.

---

# 6. 공간 기준과 좌표 처리

## 6.1 저장 좌표계

운영 테이블의 geometry는 기본적으로 `EPSG:4326`을 저장한다.

```text
위도·경도 원천
→ ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
```

거리 기반 조회가 필요한 경우 geography 변환 또는 미터 기반 투영 좌표계를 사용한다.

```sql
ST_DWithin(geom::geography, target_geom::geography, radius_m)
```

## 6.2 공간 인덱스

모든 geometry 컬럼에는 GiST 인덱스를 생성한다.

```sql
CREATE INDEX idx_osm_road_ways_geom
ON road_prod.osm_road_ways
USING GIST (geom);
```

대상:

```text
osm_road_ways.geom
osm_road_nodes.geom
road_guide_signs.geom
traffic_signals.geom
crosswalks.geom
protection_zones.geom
```

---

# 7. 검증 계획

## 7.1 공통 검증

모든 원천에 공통 적용한다.

```text
필수 컬럼 존재 여부
전체 수집 건수와 staging 건수 비교
source_id 중복률
좌표 누락률
위도·경도 범위
geometry 생성 성공률
geometry 유효성
대한민국 범위 밖 좌표 비율
기준일자 역행 여부
이전 적재 대비 건수 급감 여부
raw_json 저장 여부
```

## 7.2 OSM 검증

```text
PBF 파일 존재 여부
PBF 파일 크기 급감 여부
osm2pgsql 실행 성공 여부
highway way 건수
geometry null 건수
invalid geometry 건수
highway_type 분포
oneway·lanes·maxspeed 태그 파싱 실패율
공간 인덱스 생성 여부
대표 좌표 주변 도로 조회 성공 여부
```

대표 좌표 검증 케이스:

```text
서울 도심 교차로
부산 도심 교차로
광주 도심 교차로
고속도로 IC 부근
회전교차로
도로가 적은 농어촌 지역
```

## 7.3 공공데이터 검증

```text
원천별 전체 페이지 수집 완료 여부
원천 응답 코드 정상 여부
좌표 필드 파싱 성공률
주소만 있고 좌표가 없는 레코드 처리 여부
중복 source_id 처리 여부
동일 좌표 다중 시설 허용 여부
staging 건수와 production 건수 일치 여부
```

원천별 추가 검증:

```text
도로안내표지
→ 도로명, 노선번호, 방향안내 값 존재율

신호등
→ 차량신호등·보행자신호등 구분 가능 여부

횡단보도
→ 횡단보도 유형, 보행자신호 유무 파싱 여부

보호구역
→ 보호구역 유형, 시설명, polygon 또는 중심점 생성 여부
→ 필수 sggCd 누락 여부
→ 시군구 코드별 호출 성공 여부
→ 시군구 코드별 수집 건수 급감 여부
→ 같은 보호구역이 여러 페이지 또는 여러 조건에서 중복 수집되는지 여부
→ geometry가 Polygon인지 Point인지 구분 가능 여부
→ geometry가 없을 때 중심점 좌표 대체 가능 여부
```

## 7.4 보호구역 전용 검증

보호구역 API는 `sggCd`가 필수이므로 전체 수집 완료 여부를 단순 총건수만으로 판단하지 않는다. 시군구 코드별 성공 여부를 따로 기록한다.

검증 항목:

```text
PROTECTION_ZONE_SGG_CODES가 비어 있지 않은지
각 sggCd 호출이 200 응답인지
각 sggCd 응답에 정상 결과 코드가 있는지
각 sggCd의 pageNo 반복이 끝까지 수행됐는지
각 sggCd별 received_count가 기록됐는지
sggCd별 실패 목록이 별도 로그에 남는지
실패한 sggCd가 있으면 production 교체를 중단할지, 부분 적재로 둘지 정책이 정해졌는지
```

V1 기본 정책:

```text
전국 전체 적재 모드
→ 하나 이상의 sggCd 실패 시 production 교체 중단

개발 테스트 모드
→ 지정한 일부 sggCd만 성공하면 preview 또는 staging 테스트 허용
```

적재 로그에는 전체 실행 로그 외에 시군구별 상세 로그를 남긴다.

권장 테이블:

```text
road_meta.source_sync_logs
road_meta.source_sync_detail_logs
```

`source_sync_detail_logs` 권장 컬럼:

```text
detail_id
sync_id
source_name
sgg_cd
page_no
status
received_count
error_message
started_at
finished_at
```

---

# 8. 운영 반영 조건

검증이 모두 통과해야 production 교체를 수행한다.

최소 통과 조건:

```text
필수 테이블 적재 성공
geometry 유효성 치명 오류 없음
이전 대비 건수 급감 없음
공간 인덱스 생성 성공
대표 좌표 조회 성공
source_sync_logs 기록 성공
보호구역은 대상 sggCd 전체 성공 또는 명시적 부분 적재 모드 확인
```

검증 실패 시:

```text
production 교체 중단
기존 production 유지
실패 원인 기록
rejected 데이터 저장
source_quality_reports 저장
알림 또는 로그 출력
```

V1 품질 목표:

```text
배치 실패 시 기존 운영 테이블 보존: 100%
출력 JSON Schema 통과율: 100%
위치 모호 사례 임의 확정: 0건
판정근거 없는 확정 판정: 0건
근거 없는 필드 생성: 0건
```

---

# 9. 적재 이력 관리

적재 실행마다 이력을 남긴다.

```text
road_meta.source_sync_logs
```

권장 컬럼:

```text
sync_id
source_name
source_type
started_at
finished_at
status
received_count
staging_count
production_count
rejected_count
source_reference_date
snapshot_path
pipeline_version
error_message
```

품질검증 결과는 별도 테이블에 저장한다.

```text
road_meta.source_quality_reports
```

권장 컬럼:

```text
report_id
sync_id
check_name
severity
status
metric_value
threshold_value
message
created_at
```

---

# 10. MCP 조회 검증

데이터 적재가 끝났다고 MCP가 바로 신뢰 가능한 것은 아니다. 실제 도구 호출 기준으로 검증한다.

## 10.1 입력 검증

```text
사고위치 필수 문자열
위치확정방식 enum 검증
확정좌표 위도·경도 범위 검증
검색 또는 지도선택 상태에서 좌표 필수 검증
대화입력 상태에서 VWorld 검색 수행 여부
```

## 10.2 위치 후보 검증

```text
VWorld 단일 후보
→ 같은 호출에서 PostGIS 조회 진행

VWorld 다중 후보
→ 위치확인필요 반환
→ 검색후보 목록 포함
→ PostGIS 분석 미수행

VWorld 검색결과 없음
→ 조회불가 또는 위치정보부족 반환
```

## 10.3 PostGIS 조회 검증

```text
사고좌표 반경 N미터 내 도로 조회
가장 가까운 기준도로 후보 산출
신호등·횡단보도 근접조회
보호구역 포함 여부 판정
도로안내표지 근접조회
조회결과의 근거 필드 포함
```

## 10.4 출력 검증

모든 결과는 `road_environment_output_v1` 스키마를 통과해야 한다.

```text
성공
위치확인필요
조회불가
정보부족
```

모든 상태에서 고정 출력 구조를 유지한다.

---

# 11. 테스트 데이터 세트

최소 테스트 장소 유형:

```text
일반 직선도로
곡선도로
십자형 사거리
T자형 삼거리
Y자형 삼거리
회전교차로
도로 분기
도로 합류
고속도로 진입램프
고속도로 진출램프
어린이보호구역
신호등과 횡단보도 인접 지점
같은 장소명이 여러 지역에 있는 사례
검색 결과가 없는 장소명
```

각 테스트 케이스는 다음 정보를 가진다.

```text
case_id
입력 사고위치
위치확정방식
기대 상태
기대 기준도로 유형
기대 시설 존재 여부
기대 보호구역 여부
검증 메모
```

---

# 12. 단계별 실행 계획

## 1단계: Swagger URL·파라미터 확정

```text
공공데이터 4종 Swagger 화면 확인
Base URL + GET 경로를 .env에 입력
serviceKey는 PUBLIC_DATA_API_KEY로만 관리
pageNo, numOfRows는 URL에 붙이지 않음
보호구역은 sggCd 필수 확인
보호구역 테스트용 sggCd 1개 입력
```

결과물:

```text
ROAD_SIGNS_API_URL
TRAFFIC_SIGNALS_API_URL
CROSSWALKS_API_URL
PROTECTION_ZONES_API_URL
PROTECTION_ZONE_SGG_CODES
```

## 2단계: API 1건 미리보기

```text
각 API를 pageNo=1, numOfRows=1로 호출
응답 JSON 원본 저장
목록 배열 위치 확인
전체 건수 필드 확인
좌표·geometry 필드 확인
정규화 매핑표 작성
```

보호구역은 다음 조건으로 먼저 확인한다.

```text
PROTECTION_ZONES_API_URL
PUBLIC_DATA_API_KEY
PROTECTION_ZONE_SGG_CODES 첫 번째 값
pageNo=1
numOfRows=1
```

## 3단계: DB 준비

```text
road-postgis 컨테이너 생성
PostGIS 확장 활성화
road_prod, road_staging, road_meta 스키마 생성
공간 인덱스 생성 테스트
```

## 4단계: OSM 적재

```text
대한민국 PBF 다운로드
osm2pgsql Flex 작성
staging 적재
OSM 품질검증
production 교체
대표 좌표 주변 도로 조회 테스트
```

## 5단계: 공공데이터 4종 적재

```text
API 키와 활용신청 상태 확인
페이지네이션 수집기 구현
raw_json snapshot 저장
정규화 및 geometry 생성
staging 적재
품질검증
production 교체
```

보호구역은 추가로 다음을 수행한다.

```text
시군구 코드 목록 준비
sggCd별 페이지네이션 반복
sggCd별 성공·실패 로그 저장
실패 sggCd가 있으면 전국 production 교체 중단
```

## 6단계: MCP 조회 검증

```text
VWorld 단일·다중·미검색 케이스 테스트
PostGIS 주변 조회 테스트
출력 JSON Schema 테스트
Supervisor 재질문 흐름 테스트
```

## 7단계: 운영 반복

```text
공공데이터 4종: 원천 갱신주기에 맞춰 주간 또는 월간 적재
OSM PBF: V1에서는 주 1회 또는 월 1회 전체 교체
실패 시 기존 production 유지
적재 이력과 품질 리포트 보존
```

---

# 13. 결정 사항

- OSM PBF 적재본이 핵심 운영데이터다.
- 공공데이터 4종은 교통시설과 규제 환경을 보완한다.
- VWorld는 위치 검색·선택을 위한 실시간 서비스로만 사용한다.
- Overpass API는 운영 분석의 주 원천이 아니라 특정 지점 확인용 선택 도구다.
- 모든 원천은 staging 검증 후 production에 반영한다.
- 검증 실패 시 production을 교체하지 않는다.
- MCP는 위치 모호 사례를 임의 확정하지 않는다.
- 최종 출력은 항상 `road_environment_output_v1` 구조를 유지한다.
