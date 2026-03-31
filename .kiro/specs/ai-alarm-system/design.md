# 기술 설계 문서: AI Alarm System (POC)

## 개요

AI Alarm System POC는 Client-Server 구조로, Client가 로컬 이미지를 Server에 전송하면 Server가 Azure Document Intelligence(DI)와 Azure OpenAI GPT-4o Vision을 병렬로 활용하여 화면 상태를 분석하고 판단 결과(OK/NG/UNKNOWN)를 반환하는 시스템이다.

## 분석 파이프라인

```
전체 이미지 (1920x1170)
        │
        ▼
  4개 패널 크롭 (1회, DI와 LLM이 공유)
  ┌──────────────────────────────────────┐
  │ top_left  top_right  bottom_left  bottom_right │
  └──────────────────────────────────────┘
        │                       │
        ▼ (병렬)                 ▼ (병렬)
  ┌──────────────┐       ┌──────────────┐
  │     DI       │       │     LLM      │
  │  S520 숫자   │       │  S520 색상   │
  │  S530 숫자   │       │  S530 색상   │
  │  S810 숫자   │       │  S540 색상   │
  │ (WHITE row)  │       │  S810 색상   │
  └──────────────┘       └──────────────┘
        │                       │
        ▼                       ▼
  숫자 추출 결과           색상 감지 결과
  (NG if >= 3000)         (NG if RED 영역)
        │                       │
        └──────────┬────────────┘
                   ▼
             최종 판정 병합
             - 숫자 NG 항목 (DI)
             - 색상 NG 항목 (LLM)
             - 전체 status (OK/NG/UNKNOWN)
             - reasoning + log
```

### DI 검증 (UNKNOWN 조기 반환)
DI 추출 후 장비 ID 누락 시 LLM 호출 없이 즉시 UNKNOWN 반환:
- 추출된 부분 데이터를 `equipment_data`에 포함하여 로그 기록
- 이메일 알림 발송 (SNS_ENABLED=true 시)
- 값 개수 검증은 OCR 오류 내성을 위해 제거됨 (`_check_di_value_counts` no-op)

### S540 화면 모드 감지
S540 패널이 정상 3D 스테이션 레이아웃이 아닌 다른 화면(Setup & Parameters 등)을 표시하면 UNKNOWN 반환. S510은 Operation Mode 화면도 정상으로 허용 (wrong screen 체크 대상 아님).

## 아키텍처

### 기술 스택

| 구성요소 | 기술 |
|---------|------|
| Client GUI | Python 3.12.9, tkinter |
| Server | Python 3.12.9, Flask, waitress (Windows) |
| OCR / 숫자 추출 | Azure Document Intelligence (`prebuilt-layout`) |
| 색상 감지 | Azure OpenAI GPT-4o Vision via `langchain-openai` |
| HTTP 통신 | requests |
| 설정 관리 | PyYAML + python-dotenv |
| 알림 | AWS SNS API Gateway |

### 주요 의존성

```
flask
waitress
requests
langchain-openai
python-dotenv
PyYAML
Pillow
azure-ai-formrecognizer
azure-core
```

## 컴포넌트 및 인터페이스

### 1. Client (Mock Tester GUI)

#### 모듈 구조

```
client/
├── main.py              # GUI 진입점
├── gui.py               # tkinter GUI (Analysis/History 탭, Batch 분석)
├── api_client.py        # Server HTTP 통신 (재시도 3회)
├── periodic_runner.py   # 주기적 요청 관리
├── history_logger.py    # CSV 분석 이력 기록 (data/client_history.csv)
└── models.py            # 데이터 모델 (server.models re-export)
```

#### 테스트 이미지 폴더 구조

```
test_images/
├── ok/        ← OK로 판단되어야 하는 이미지
├── ng/        ← NG로 판단되어야 하는 이미지
├── unknown/   ← UNKNOWN으로 판단되어야 하는 이미지
└── batch/     ← 분류 전 대량 이미지 (Analyze Batch 대상)
```

#### Batch 분석 기능
- `test_images/batch/` 폴더의 이미지를 서버로 전송하여 분석
- 결과에 따라 `batch/ok/`, `batch/ng/`, `batch/unknown/` 하위 폴더로 이미지 **이동**
- 각 이미지와 동일한 이름의 `.json` 파일(응답 데이터)을 같은 폴더에 저장
- Random 옵션: 체크박스 + 숫자 입력으로 N개 랜덤 샘플링 후 실행

### 2. Server (Flask)

#### 모듈 구조

```
server/
├── main.py                      # Flask 앱 진입점
├── config.py                    # 설정 로드 (YAML + .env)
├── models.py                    # 데이터 모델
├── logger.py                    # 결과 저장 + 판정 로그
├── prompt_config.yaml           # LLM 색상 감지 프롬프트
├── server_config.yaml           # 서버 설정
├── .env                         # Azure 자격증명 (gitignored)
├── api/
│   └── routes.py                # Flask API 라우트
└── services/
    ├── llm_service.py           # DI+LLM 병렬 파이프라인
    ├── document_intelligence.py # Azure DI 숫자 추출 (4패널 병렬)
    ├── image_validator.py       # PNG/JPEG 검증
    └── email_notifier.py        # UNKNOWN 알림 (SNS)
```

#### API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/analyze` | 단건 이미지 분석 |
| GET | `/api/v1/health` | 서버 상태 확인 |

#### 분석 응답 형식

```json
{
  "request_id": "req_20240101_120000_0001",
  "status": "OK | NG | UNKNOWN | TIMEOUT",
  "reason": "한국어 판단 이유",
  "timestamp": "2024-01-01T12:00:00",
  "processing_time_ms": 7200,
  "equipment_data": {
    "S520": {
      "identified": true,
      "curing_oven": [2887, 2767, ...],
      "preheating_oven": [0, 124, ...],
      "color_reasoning": "...",
      "ng_items": []
    },
    "S530": { ... },
    "S540": {
      "identified": true,
      "color_reasoning": "Station 6-1 has red background.",
      "ng_items": ["RED [center, station label '6-1']: 6-1"]
    },
    "S810": { ... }
  }
}
```

### 3. Document Intelligence Service

```
document_intelligence.py
├── _crop_panel()           # 이미지를 4개 패널로 크롭
├── _parse_di_result()      # DI 결과 파싱 (sub_label 기반 테이블 레이블링)
├── _normalize_field_name() # sub_label → 표준 필드명 변환
├── ExtractedTable
│   ├── white_row_values()  # WHITE row(3번째 행) 숫자 값 리스트 반환
│   └── infer_field_name()  # sub_label 기반 필드명 추론
└── DocumentIntelligenceService
    └── extract()           # 4패널 병렬 DI 호출
```

**핵심 설계 원칙:**
- 헤더 키(1#, 2#...)는 무시 — OCR 오류에 취약
- WHITE row(row index 2)의 숫자 값만 추출
- 3000 이상 여부만 확인하면 되므로 순서/방향 무관

### 4. LLM Service

```
llm_service.py
├── _validate_di_result()         # DI 결과 검증 (장비 ID 누락만 확인)
├── _check_di_value_counts()      # no-op — 값 개수 검증 제거 (OCR 오류 내성)
├── _build_partial_equipment_data() # UNKNOWN 시 부분 데이터 조립
├── LLMService
│   ├── analyze_image()           # 메인 진입점
│   ├── _analyze_di_plus_llm()    # DI+LLM 병렬 파이프라인
│   ├── _detect_color()           # 단일 패널 색상 감지 (LLM)
│   ├── _merge_results()          # DI 숫자 + LLM 색상 병합
│   └── _analyze_vision_only()    # DI 미설정 시 fallback
```

## 데이터 모델

```python
class JudgmentStatus(str, Enum):
    OK = "OK"
    NG = "NG"
    UNKNOWN = "UNKNOWN"
    TIMEOUT = "TIMEOUT"

@dataclass
class JudgmentResult:
    request_id: str
    status: JudgmentStatus
    reason: str
    timestamp: str
    processing_time_ms: int = 0
    image_name: str = ""
    equipment_data: Optional[dict] = None
```

## 설정

### .env

```env
# Azure OpenAI (색상 감지 LLM)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
API_VERSION=2024-12-01-preview
VISION_MODEL=gpt-4o-korea-rag

# Azure Document Intelligence (숫자 추출 OCR)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-di-key

# SNS 알림
SNS_ENABLED=true
SNS_API_URL=https://your-api-gateway.amazonaws.com/prod
SNS_TOPIC_ARN=arn:aws:sns:region:account:topic
```

## 데이터 저장

```
data/
├── results/          # JSON 판정 결과 (debug 모드에서만 저장)
├── logs/             # 일별 로그 YYYY-MM-DD.log (항상 기록)
└── unknown_images/   # UNKNOWN 이미지 (debug 모드에서만 저장)
```

> `--dev` 플래그 없이 실행 시 results/unknown_images 파일은 저장되지 않습니다.

## 장비별 NG 판정 기준

| 장비 | 분석 방식 | NG 조건 | UNKNOWN 조건 |
|------|----------|---------|-------------|
| S520 (Preheating & Curing) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |
| S530 (Cooling) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |
| S540 (Robot) | LLM 색상 감지 전용 (3D 레이아웃 + wrong screen 체크) | RED/BLACK 스테이션 배경 | 장비 ID 미식별 또는 wrong screen |
| S510 (Robot 1) | LLM 색상 감지 전용 (RED 영역 감지) | RED 영역 감지 | 장비 ID 미식별 |
| S310 (Hairpin Insertion) | LLM 색상 감지 전용 (RED 영역 감지) | RED 영역 감지 | 장비 ID 미식별 |
| S810 (Housing Cooling) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |

> 숫자 NG 임계값: 기본 3500 (`NUMERIC_NG_THRESHOLD` 환경변수로 변경 가능)
> S540 wait count NG 임계값: 기본 1200 (`S540_WAIT_NG_THRESHOLD` 환경변수로 변경 가능)
> S510/S310은 DI 없이 LLM RED 감지만 사용. wrong screen 체크는 S540 전용.

## 오류 처리

| 오류 유형 | 처리 방식 |
|-----------|----------|
| 이미지 형식 오류 | 400 Bad Request |
| DI 장비 미식별 | UNKNOWN + 이메일 알림 |
| S540 wrong screen | UNKNOWN + 이메일 알림 |
| LLM 타임아웃 | TIMEOUT 상태 반환 |
| LLM 응답 파싱 실패 | UNKNOWN 처리 |
| 설정 파일 누락 | 서버 시작 중단 |

## 비용 추정 (10초 간격 기준)

| 간격 | 일 요청수 | DI ($/일) | LLM ($/일) | 합계 ($/일) |
|------|----------|-----------|-----------|------------|
| 10초 | 8,640 | $346 | $161 | **$507** |
| 30초 | 2,880 | $115 | $54 | **$169** |
| 60초 | 1,440 | $58 | $27 | **$85** |

> DI: $0.01/페이지 × 4패널, GPT-4o: 입력 $2.50/1M + 출력 $10/1M 기준
