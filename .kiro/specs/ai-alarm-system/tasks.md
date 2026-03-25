# 구현 계획: AI Alarm System (POC)

## 개요

Client-Server 구조의 AI Alarm System POC를 구현한다. Server(Flask + waitress)가 Azure OpenAI Vision API로 HMI 패널 이미지를 분석하고, Client(tkinter GUI)가 이미지를 전송하여 결과를 확인한다. P0 → P1 → P2 순서로 구현하며, 각 단계가 이전 단계 위에 점진적으로 빌드된다.

## Tasks

- [x] 1. 프로젝트 구조 및 공통 모듈 설정
  - [x] 1.1 프로젝트 디렉토리 구조 생성 및 의존성 설정
    - `server/`, `client/`, `tests/unit/`, `tests/property/` 디렉토리 생성
    - `requirements.txt` 작성 (flask, waitress, requests, langchain-openai, python-dotenv, PyYAML, hypothesis, pytest)
    - `.gitignore`에 `.env`, `data/`, `__pycache__/` 추가
    - `server/.env.example` 템플릿 파일 생성
    - _Requirements: 4.1, 5.1_

  - [x] 1.2 공유 데이터 모델 구현 (`server/models.py`)
    - `JudgmentStatus` Enum (OK, NG, UNKNOWN, TIMEOUT)
    - `JudgmentResult` dataclass (`to_dict()`, `from_dict()` 포함)
    - `ValidationResult`, `LLMResponse` dataclass
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

  - [ ]* 1.3 JudgmentResult 라운드트립 속성 테스트 작성
    - **Property 2: JudgmentResult 직렬화 라운드트립**
    - Hypothesis로 임의의 JudgmentResult 생성 후 `to_dict()` → `from_dict()` 라운드트립 검증
    - TIMEOUT 상태 및 `processing_time_ms` 필드 포함
    - **Validates: Requirements 6.4, 6.5**

- [x] 2. Server 핵심 구현 (P0)
  - [x] 2.1 설정 로드 모듈 구현 (`server/config.py`)
    - `prompt_config.yaml` 로드 및 검증 (PyYAML)
    - `.env` 로드 (python-dotenv)
    - 설정 파일 누락/형식 오류 시 서버 시작 중단
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 2.2 프롬프트 설정 파일 작성 (`server/prompt_config.yaml`)
    - 설계 문서의 `prompt_config.yaml` 내용 그대로 작성
    - 장비별 판단 조건 (S520, S530, S540, S810) 포함
    - 응답 형식 JSON 스키마 포함
    - _Requirements: 4.2, 5.1_

  - [x] 2.3 이미지 검증 모듈 구현 (`server/services/image_validator.py`)
    - `ImageValidator.validate()` — PNG/JPEG 형식 및 20MB 크기 제한 검증
    - _Requirements: 3.2, 3.3_

  - [ ]* 2.4 이미지 형식 검증 속성 테스트 작성
    - **Property 1: 이미지 형식 검증**
    - Hypothesis로 임의의 바이트 + 파일 확장자 생성하여 검증 로직 테스트
    - **Validates: Requirements 3.2, 3.3**

  - [x] 2.5 LLM Service 구현 (`server/services/llm_service.py`)
    - `get_azure_vision_llm()` 팩토리 함수
    - `LLMService.__init__()` — AzureChatOpenAI 클라이언트 초기화
    - `LLMService.analyze_image()` — base64 인코딩, LangChain HumanMessage 구성, 타임아웃 관리
    - `LLMService._build_prompt()` — PromptConfig 기반 프롬프트 생성
    - `LLMService._parse_response()` — JSON 파싱, 실패 시 UNKNOWN 처리
    - _Requirements: 4.1, 4.2, 4.3, 6.1, 6.3_

  - [ ]* 2.6 LLM 응답 파싱 속성 테스트 작성
    - **Property 3: LLM 응답 파싱 시 필수 필드 포함**
    - **Property 4: 잘못된 JSON 응답은 Unknown 처리**
    - Hypothesis로 유효/무효 JSON 응답 생성하여 파서 검증
    - **Validates: Requirements 6.1, 6.2, 6.3, 9.2**

  - [ ]* 2.7 프롬프트 판단 조건 포함 속성 테스트 작성
    - **Property 5: 프롬프트에 판단 조건 포함**
    - PromptConfig의 OK/NG/Unknown 조건이 빌드된 프롬프트에 포함되는지 검증
    - **Validates: Requirements 4.2**

  - [x] 2.8 Flask API 라우트 구현 (`server/api/routes.py`)
    - `POST /api/v1/analyze` — multipart/form-data 이미지 수신, 검증, LLM 분석, 결과 반환
    - `GET /api/v1/health` — 서버 상태 확인
    - 오류 응답 형식 (INVALID_IMAGE_FORMAT, IMAGE_TOO_LARGE, LLM_SERVICE_ERROR 등)
    - `processing_time_ms` 필드 포함
    - _Requirements: 3.1, 3.3, 4.4, 9.1, 9.2_

  - [x] 2.9 Server 진입점 구현 (`server/main.py`)
    - Flask 앱 생성 및 라우트 등록
    - 설정 로드 및 검증
    - waitress 또는 Flask 내장 서버로 실행
    - _Requirements: 5.2, 5.3_

- [x] 3. 체크포인트 — Server P0 검증
  - Server가 정상 기동되고, `/api/v1/health` 응답 확인
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 확인

- [x] 4. Client GUI 구현 (P0)
  - [x] 4.1 API Client 모듈 구현 (`client/api_client.py`)
    - `AlarmApiClient.__init__()` — base_url, request_timeout 설정
    - `AlarmApiClient.analyze_single()` — 단건 이미지 분석 요청 (multipart/form-data)
    - `AlarmApiClient.health_check()` — 서버 상태 확인
    - _Requirements: 2.1, 2.2, 9.3_

  - [ ]* 4.2 요청 메타데이터 속성 테스트 작성
    - **Property 6: 요청 메타데이터 포함**
    - 분석 요청에 타임스탬프와 고유 request_id가 포함되는지 검증
    - **Validates: Requirements 2.2**

  - [x] 4.3 주기적 요청 관리 모듈 구현 (`client/periodic_runner.py`)
    - `PeriodicRunner` — start/stop/set_interval/is_running
    - 별도 스레드에서 주기적 분석 요청 실행 (5초/10초)
    - 콜백 함수로 결과 전달
    - _Requirements: 2.1_

  - [x] 4.4 Client 데이터 모델 구현 (`client/models.py`)
    - Server와 동일한 `JudgmentStatus`, `JudgmentResult` 모델 (또는 server/models.py 임포트)
    - _Requirements: 9.3, 9.4_

  - [x] 4.5 tkinter GUI 구현 (`client/gui.py`)
    - 테스트 이미지 폴더 선택 (폴더 브라우저, `test_images/` 하위 자동 탐색)
    - 이미지 목록 표시 (폴더명 = 기대 결과 ok/ng/unknown)
    - 단건 분석 요청 버튼
    - 주기적 요청 모드: 시작/중지 버튼, 간격 드롭다운 (5초/10초)
    - 결과 테이블: 이미지명, 기대값(expected), 판단값(actual), 일치여부(✓/✗), 판단이유, 처리시간
    - 상태별 색상 구분 (OK=초록, NG=빨강, Unknown=노랑, TIMEOUT=회색)
    - 기대값 불일치 시 행 배경색 강조
    - _Requirements: 1.1, 1.2, 9.3_

  - [x] 4.6 Client 진입점 구현 (`client/main.py`)
    - tkinter 앱 실행
    - Server URL 설정 (기본 http://localhost:8000)
    - _Requirements: 1.1_

- [x] 5. 체크포인트 — Client-Server 통합 검증
  - Client GUI에서 테스트 이미지 전송 → Server 분석 → 결과 표시 흐름 확인
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 확인

- [x] 6. 판단 결과 저장/로그 구현 (P1)
  - [x] 6.1 로그/저장 모듈 구현 (`server/logger.py`)
    - `ResultStorage` — JSON 파일 저장 (`data/results/`), Unknown 이미지 저장 (`data/unknown_images/`)
    - `JudgmentLogger` — 일별 로그 파일 기록 (`data/logs/`)
    - request_id 기반 결과 조회 기능
    - `pathlib.Path` 사용, `encoding='utf-8'` 명시
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 6.2 로그 필수 정보 속성 테스트 작성
    - **Property 7: 로그에 필수 정보 포함**
    - 로그 항목에 판단 이유, 타임스탬프, 요청 식별자가 포함되는지 검증
    - **Validates: Requirements 7.2**

  - [ ]* 6.3 request_id 기반 결과 조회 속성 테스트 작성
    - **Property 9: request_id 기반 결과 조회**
    - 저장 후 동일 request_id로 조회 시 원본과 동일한 결과 반환 검증
    - **Validates: Requirements 7.4**

  - [x] 6.4 Server API에 저장/로그 연동
    - `POST /api/v1/analyze` 응답 후 결과 저장 및 로그 기록 호출
    - Unknown 판단 시 이미지 별도 저장
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 7. 체크포인트 — P1 저장/로그 검증
  - 분석 결과가 `data/results/`에 JSON으로 저장되는지 확인
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 확인

- [x] 8. 이메일 알림 및 재시도 구현 (P2)
  - [x] 8.1 이메일 알림 모듈 구현 (`server/services/email_notifier.py`)
    - `EmailNotifier.__init__()` — SMTP 설정 로드
    - `EmailNotifier.send_alert()` — Unknown 상태 알림 이메일 전송, 최대 3회 재시도
    - 이메일 본문에 판단 이유, 타임스탬프, 요청 식별자 포함
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 8.2 이메일 본문 필수 정보 속성 테스트 작성
    - **Property 8: 이메일 본문에 필수 정보 포함**
    - Unknown 상태 JudgmentResult로 생성된 이메일 본문에 필수 정보 포함 검증
    - **Validates: Requirements 8.2**

  - [x] 8.3 Client 재시도 로직 추가 (`client/api_client.py`)
    - 전송 실패 시 최대 3회 재시도
    - 재시도 실패 시 오류 로그 기록
    - _Requirements: 2.3, 2.4_

  - [x] 8.4 Server API에 이메일 알림 연동
    - Unknown 판단 시 `EmailNotifier.send_alert()` 호출
    - 이메일 전송 실패 시 로그 기록 (응답에는 영향 없음)
    - _Requirements: 8.1_

- [x] 9. 응답 처리 시간 검증 및 최종 통합
  - [ ]* 9.1 응답 처리 시간 속성 테스트 작성
    - **Property 10: 응답에 처리 시간 포함**
    - `processing_time_ms` 필드가 0 이상 정수인지, TIMEOUT 시 타임아웃 설정값 이상인지 검증
    - **Validates: Requirements 9.2**

  - [x] 9.2 전체 모듈 연동 확인 및 최종 정리
    - Server: 설정 로드 → 이미지 수신 → 검증 → LLM 분석 → 결과 저장/로그 → 이메일 → 응답 반환 전체 흐름 연결
    - Client: 폴더 선택 → 이미지 목록 → 단건/주기적 분석 → 결과 테이블 표시 전체 흐름 연결
    - _Requirements: 전체_

- [x] 10. 최종 체크포인트
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 확인

## Notes

- `*` 표시된 태스크는 선택 사항이며 빠른 MVP를 위해 건너뛸 수 있습니다
- 각 태스크는 추적성을 위해 특정 요구사항을 참조합니다
- 체크포인트에서 점진적 검증을 수행합니다
- 속성 테스트는 보편적 정확성 속성을 검증합니다
- 단위 테스트는 특정 예제와 엣지 케이스를 검증합니다
- 모든 파일 경로는 `pathlib.Path`를 사용하여 Windows 호환성을 보장합니다
