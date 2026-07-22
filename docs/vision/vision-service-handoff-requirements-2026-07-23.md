# Vision 서비스 handoff 필수 요구사항

## 목적

#294가 기존 Vision 파이프라인을 Django Worker의 실제 `vision_media_analysis` adapter로 연결할 때 필요한 변경사항을 정리한다. 이 문서는 Vision 모델 품질 개선 계획이 아니라, 재현 가능한 서비스 연결과 안전한 결과 전달의 계약이다.

## 담당 구분

| 구분 | 책임 |
| --- | --- |
| Vision 파이프라인 | 호출 가능한 진입점, 모델·체크포인트·라벨 계약, 실행 산출물의 격리, 결과 형식 |
| #294 adapter | scan-ready 첨부 전달, Worker 실행, Agent envelope 변환, Supervisor handoff, 안전한 영속화·로그 |
| 운영 환경 | Vision 의존성, 체크포인트 접근, GPU 또는 명시적 실행 장치, 단일 영상 smoke test 실행 |

## Vision 파이프라인 필수 조치

1. **한국어 라벨 매핑 반영**
   - `origin/feat-accident-image-video-agent-result-flow`의 `09dea16`은 학습 모델의 한국어 라벨을 내부 사고 카테고리로 매핑해 YOLO 선택 실패를 막는다.
   - 이는 성능 개선이 아니라 실제 실행 정합성 수정이므로 #294 연결 전 반영하거나 동일한 테스트를 통과해야 한다.

2. **서비스 호출 가능 경계 제공**
   - 현재 `run_to_supervisor.run()`은 `Path`를 받아 파일을 쓰고 출력 경로만 반환한다.
   - adapter가 사용할 함수는 입력 영상 경로, 실행 식별자, 명시적 실행 설정을 받고 정규화된 handoff 결과를 반환해야 한다.
   - CLI entrypoint는 유지하되 Worker가 `latest_file()`이나 전역 출력 파일을 찾지 않도록 한다.

3. **실행 격리와 정리**
   - 모든 파일은 `job_id/execution_id` 단위 작업 디렉터리에서 생성한다.
   - 임시 입력과 중간 프레임은 실행 종료 후 정리하고, 보존이 필요한 증거는 안전한 참조로만 반환한다.
   - 동일한 원본 파일명으로 동시 실행해도 결과가 덮어써지면 안 된다.

4. **사전 검사와 안정된 실패 결과**
   - 실행 전 체크포인트 완전성, 필수 Python 의존성, 입력 파일 존재·해독 가능 여부, 실행 장치 설정을 검사한다.
   - 실패 결과는 `vision_checkpoint_missing`, `vision_dependency_missing`, `vision_media_decode_failed`, `vision_execution_failed` 같은 코드로 변환한다.
   - Python stack trace, 절대 경로, 모델 저장 위치, provider 원문 오류는 handoff와 사용자 응답에 포함하지 않는다.

5. **안전한 handoff contract**
   - `vision_supervisor_handoff`에는 요약, 이벤트 시점, 객체 종류 요약, 불확실성, 한계, 안전한 증거 식별자만 넣는다.
   - `source_video`, `frame_path`, `clip_path`, Qwen 원문 오류처럼 내부 경로나 민감한 원문이 될 수 있는 필드는 제거하거나 안전한 참조로 대체한다.
   - `not_determined_by_vision`의 과실비율·법적 책임·교통위반·최종 사고유형 비결정 원칙을 유지한다.

## #294 adapter 필수 조치

- `vision_media_analysis`를 mock 전용 집합에서 제외하고 sync Worker adapter로 등록한다.
- canonical scan gate를 통과한 영상만 object storage에서 Worker 전용 임시 파일로 준비한다.
- Vision 결과를 Agent output envelope로 변환해 `text_ml_case_search`와 `law_ground_search`의 upstream 결과로 제공한다.
- `job_id`, `execution_id`, `attachment_id`, adapter 상태, 실패 코드, 소요 시간만 trace에 남긴다.
- `AgentResult.raw_output`과 `AnalysisJobEvent.metadata`를 저장하기 전에 원본 바이트, OCR 원문, 사용자 전체 문장, storage/local path, 비밀값, 예외 원문을 제거한다.

## 명시적 제외

- `d3c5ed8`의 32프레임 적응형 전처리와 Qwen 입력 확대
- 새 모델·새 provider·모델 재학습
- 정확도·프레임 수·성능·비용 최적화
- 정지 이미지용 새 Vision 모델

위 항목은 #294의 연결 안정화와 별도의 품질 개선 작업으로 관리한다.

## 검증

- 라벨 매핑: 한국어 학습 라벨이 올바른 YOLO 모델로 변환된다.
- 호출 경계: 테스트 대역 Vision 실행 결과가 Agent envelope와 handoff contract를 통과한다.
- 격리: 같은 파일명·동시 실행도 작업 경로와 결과가 섞이지 않는다.
- 실패: 체크포인트, 의존성, 해독 오류가 안정된 코드로 변환되고 내부 정보가 나오지 않는다.
- 실환경: 체크포인트·의존성·실행 장치가 준비된 환경에서 단일 MP4가 실제 handoff 결과를 생성한다.
