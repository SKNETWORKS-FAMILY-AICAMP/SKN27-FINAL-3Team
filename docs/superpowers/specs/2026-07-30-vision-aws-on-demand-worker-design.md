# 온디맨드 AWS Vision GPU Worker 설계

## 목표

기존 Vision handoff 계약을 유지하면서 RunPod 의존성을 AWS GPU EC2 worker로 대체하고, 영상 분석 요청이 없으면 GPU 인스턴스를 중지한다.

## 범위

- backend provider는 signed S3 video URL과 execution id를 비동기 작업으로 제출한다.
- SQS queue/DLQ와 결과 상태 저장소를 통해 요청·재시도·결과 조회를 분리한다.
- controller는 새 작업에서 GPU EC2를 시작하고, worker는 private network에서 queue를 poll한다.
- idle controller는 진행 중인 작업이 없고 유휴 시간이 지나면 instance를 정상 중지한다.
- worker는 기존 `vision-supervisor-handoff-v1`만 반환하고 signed URL, 경로, 비밀값을 로그·결과에 남기지 않는다.

## 경계

GPU instance, IAM, queue, controller는 Terraform으로 선언하지만 실제 AWS 생성·GPU 비용 발생은 별도 apply 승인 뒤에만 일어난다. Vision은 비동기이며 cold start 동안 UI는 job 상태를 표시한다.

## 성공 기준

1. 잘못된 요청은 worker 기동 없이 안전한 오류 코드로 끝난다.
2. 같은 execution id는 중복 GPU 작업을 만들지 않는다.
3. 유휴 정지는 실행 중 작업을 중단하지 않는다.
4. 기존 RunPod provider는 명시적으로 선택될 때까지 계속 동작한다.
