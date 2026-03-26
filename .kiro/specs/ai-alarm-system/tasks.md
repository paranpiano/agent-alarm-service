# 구현 계획: AI Alarm System (POC)

## 개요

Client-Server 구조의 AI Alarm System POC를 구현한다. Azure Document Intelligence(DI)로 숫자를 추출하고, Azure OpenAI GPT-4o Vision으로 색상을 감지하여 HMI 패널 이미지를 분석한다.

## Tasks

- [x] 1. 프로젝트 구조 및 공통 모듈 설정
  - [x] 1.1 프로젝트 디렉토리 구조 생성 및 의존성 설정
  - [x] 1.2 공유 데이터 모델 구현 (`server/models.py`)

- [x] 2. Server 핵심 구현
  - [x] 2.1 설정 로드 모듈 (`server/config.py`) — DI, SNS_ENABLED 포함
  - [x] 2.2 이미지 검증 모듈 (`server/services/image_validator.py`)
  - [x] 2.3 Flask API 라우트 (`server/api/routes.py`) — debug 모드 저장 분기
  - [x] 2.4 Server 진입점 (`server/main.py`)

- [x] 3. Document Intelligence 서비스
  - [x] 3.1 4패널 크롭 + 병렬 DI 호출 (`server/services/document_intelligence.py`)
  - [x] 3.2 WHITE row 숫자 추출 (`white_row_values`) — 헤더 키 무관, 순서 무관
  - [x] 3.3 sub_label 기반 필드명 추론 (`infer_field_name`, `_normalize_field_name`)
  - [x] 3.4 bounding region y좌표 기반 테이블 레이블링 (`sub_label`)

- [x] 4. LLM Service — DI+LLM 병렬 파이프라인
  - [x] 4.1 DI 검증 (`_validate_di_result`) — 장비 ID 누락만 확인 (값 개수 검증 제거)
  - [x] 4.2 색상 감지 전용 프롬프트 (`_COLOR_DETECTION_PROMPT`)
    - 노란 배경 느낌표 아이콘 무시
    - S540 wrong screen 감지 (Setup & Parameters 등)
  - [x] 4.3 결과 병합 (`_merge_results`) — equipment_id 정규화, first-match-wins
  - [x] 4.4 Vision-only fallback (DI 미설정 시)
  - [x] 4.5 단일 패널 모드 지원 (`single_panel=True`) — 자동 감지 (픽셀 수 기준)

- [x] 5. Client GUI
  - [x] 5.1 API Client (`client/api_client.py`) — 재시도 3회
  - [x] 5.2 tkinter GUI (`client/gui.py`)
    - Analysis / History 탭
    - Analyze Selected / Analyze All / Analyze Batch 버튼
    - Refresh 버튼 (트리 새로고침)
    - Random 옵션 (체크박스 + N개 입력)
  - [x] 5.3 Batch 분석 — 이미지 이동 + JSON 저장
  - [x] 5.4 트리뷰에 batch 폴더 표시
  - [x] 5.5 CSV 이력 기록 (`client/history_logger.py`) — `data/client_history.csv`

- [x] 6. 판단 결과 저장/로그
  - [x] 6.1 `server/logger.py` — debug 모드에서만 파일 저장, 로그는 항상 기록
  - [x] 6.2 UNKNOWN 시 equipment_data 로그 기록

- [x] 7. 알림
  - [x] 7.1 SNS 알림 (`server/services/email_notifier.py`) — SNS_ENABLED 토글
  - [x] 7.2 UNKNOWN 시 이메일 발송 + equipment_data 로그

- [x] 8. prompt_config.yaml 업데이트
  - [x] 8.1 LLM 색상 감지 전용 스키마로 변경 (숫자 필드 제거)
  - [x] 8.2 S540 wrong screen 판단 기준 추가

- [x] 9. 문서 업데이트
  - [x] 9.1 README.md — 새 아키텍처 다이어그램
  - [x] 9.2 README_BUSINESS.md — 파이프라인 설명
  - [x] 9.3 design.md — 현재 문서
  - [x] 9.4 tasks.md — 현재 문서

## Notes

- DI WHITE row 추출은 헤더 키(1#, 2#...)를 무시하고 숫자 값만 추출 — OCR 오류 내성
- 값 개수 검증(`_check_di_value_counts`)은 no-op으로 변경 — OCR 누락 셀로 인한 오탐 방지
- 3000 이상 여부만 확인하므로 값의 순서/방향 무관
- debug 모드(`--dev`)에서만 results/unknown_images 파일 저장
- SNS_ENABLED=false로 알림 비활성화 가능
- Batch 분석 시 원본 이미지는 결과 폴더로 이동 (복사 아님)
- 단일 패널 이미지는 픽셀 수 기준으로 자동 감지 (< 1,000,000 px → single panel)
