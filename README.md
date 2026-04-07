# AI Alarm System (POC)

HMI 패널 이미지를 Azure Document Intelligence + Azure OpenAI Vision으로 분석하여 제조 장비 상태를 자동 판단하는 시스템.

## Architecture

```
Client (tkinter GUI)
        │
        ▼
Server (Flask REST API)
        │
        ▼
  단일 패널 이미지 (960x585)
        │
        ├──────────────────────────────┐
        ▼ (병렬)                       ▼ (병렬)
  ┌──────────────┐             ┌──────────────┐
  │     DI       │             │     LLM      │
  │  S520 숫자   │             │  S520 색상   │
  │  S530 숫자   │             │  S530 색상   │
  │  S810 숫자   │             │  S540 색상   │
  │ (테이블 OCR) │             │  S810 색상   │
  └──────────────┘             └──────────────┘
        │                             │
        ▼                             ▼
  숫자 추출 결과               색상 감지 결과
  (NG if >= 3000)             (NG if RED 영역)
        │                             │
        └──────────────┬──────────────┘
                       ▼
                 최종 판정 병합
                 - 숫자 NG 항목 (DI)
                 - 색상 NG 항목 (LLM)
                 - 전체 status (OK/NG/UNKNOWN)
                 - reasoning + log
```

### DI 검증 (UNKNOWN 조기 반환)

DI 추출 후 장비 ID 누락 시 LLM 호출 없이 즉시 UNKNOWN 반환:
- 추출된 부분 데이터를 `equipment_data`에 포함하여 로그에 기록
- 이메일 알림 발송 (SNS_ENABLED=true 시)
- 값 개수 검증은 OCR 오류 내성을 위해 제거됨 (장비 ID 누락만 검증)

### S540 화면 모드 감지

S540 패널이 정상 3D 스테이션 레이아웃이 아닌 다른 화면(Setup & Parameters, Machine Parameter 등)을 표시하면 UNKNOWN 반환. S510은 Operation Mode 화면도 정상으로 허용.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12.9 |
| Server | Flask + waitress (Windows) |
| OCR / 숫자 추출 | Azure Document Intelligence (`prebuilt-layout`) |
| 색상 감지 | Azure OpenAI GPT-4o Vision via `langchain-openai` |
| Client GUI | tkinter |
| Config | PyYAML + python-dotenv |
| Tests | pytest + hypothesis |

## Project Structure

```
├── server/
│   ├── main.py                  # Server entry point
│   ├── config.py                # Config loader (YAML + .env)
│   ├── models.py                # Shared data models
│   ├── logger.py                # Result storage + judgment logger
│   ├── prompt_config.yaml       # LLM 색상 감지 프롬프트 (숫자 스키마 제거됨)
│   ├── server_config.yaml       # Server settings
│   ├── .env                     # Azure credentials (gitignored)
│   ├── api/
│   │   └── routes.py            # Flask API routes
│   └── services/
│       ├── llm_service.py       # DI+LLM 병렬 파이프라인
│       ├── document_intelligence.py  # Azure DI 숫자 추출 (4패널 병렬)
│       ├── image_validator.py   # PNG/JPEG validation
│       └── email_notifier.py    # UNKNOWN status SNS alerts
├── client/
│   ├── main.py                  # GUI entry point
│   ├── gui.py                   # tkinter Mock Tester GUI
│   ├── api_client.py            # HTTP client (retry 3x)
│   ├── periodic_runner.py       # Periodic request runner (5s/10s)
│   ├── history_logger.py        # CSV 분석 이력 기록 (data/client_history.csv)
│   └── models.py                # Re-exported data models (server.models)
├── test_images/
│   ├── ok/                      # Expected OK images
│   ├── ng/                      # Expected NG images
│   └── unknown/                 # Expected UNKNOWN images
├── tests/
│   ├── unit/                    # Unit tests
│   └── property/                # Property-based tests (optional)
├── Arduino_Part/
│   ├── led_server.py           # Arduino LED control server (Flask)
│   ├── led_control.ino          # Arduino LED control sketch
│   └── README.md                # Arduino setup instructions
└── requirements.txt
```

## Arduino LED Control

Arduino를 이용한 LED 상태 표시 시스템. 서버 상태에 따라 RGB LED 색상을 변경합니다.

- **서버**: `Arduino_Part/led_server.py` (Flask, 포트 5000)
- **하드웨어**: Arduino 보드 + RGB LED
- **기능**:
  - `/status` 엔드포인트로 상태 업데이트 (normal/warning/ng/off)
  - `/color` 엔드포인트로 직접 RGB 제어
  - 타임아웃 기능: 40초 동안 신호 없으면 자동 LED 끄기
- **설정**: Arduino IDE로 `led_control.ino` 업로드, COM 포트 확인

## Recent Changes

- **2026-03-31**: `led_server.py`에서 타임아웃을 30초에서 40초로 변경
```

## Quick Start

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 2. Configure environment

Edit `server/.env`:

```env
# Azure OpenAI (색상 감지 LLM)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
API_VERSION=2024-12-01-preview
VISION_MODEL=gpt-4o-korea-rag

# Azure Document Intelligence (숫자 추출 OCR)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-di-key

# SNS 알림 (UNKNOWN 시 이메일)
SNS_ENABLED=true
SNS_API_URL=https://your-api-gateway.amazonaws.com/prod
SNS_TOPIC_ARN=arn:aws:sns:region:account:topic-name
```

### 3. Start the server

```bash
# Development mode (results/unknown_images 파일 저장 활성화)
python -m server.main --dev

# Production mode (waitress, 파일 저장 비활성화)
python -m server.main
```

### 4. Start the client GUI

```bash
python -m client.main
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/analyze` | Analyze a single image (multipart/form-data) |
| GET | `/api/v1/health` | Server health check |

### POST /api/v1/analyze

Request: `multipart/form-data` with `image` file and optional `request_id`.

Response:
```json
{
  "request_id": "req_20240101_120000_0001",
  "status": "OK",
  "reason": "모든 장비 정상입니다.",
  "timestamp": "2024-01-01T12:00:00",
  "processing_time_ms": 7200,
  "equipment_data": {
    "S520": {
      "identified": true,
      "curing_oven": {"1": 2887, "2": 2767, "...": "..."},
      "preheating_oven": {"14": 1388, "...": "..."},
      "color_reasoning": "No red areas detected.",
      "ng_items": []
    },
    "S540": {
      "identified": true,
      "color_reasoning": "Station 6-1 has red background.",
      "ng_items": ["RED [center, station label '6-1']: 6-1"]
    }
  }
}
```

Status values: `OK`, `NG`, `UNKNOWN`, `TIMEOUT`

## Equipment & Judgment Criteria

4개 장비 패널을 단일 HMI 스크린샷에서 분석:

| 장비 | 분석 방식 | NG 조건 | UNKNOWN 조건 |
|------|----------|---------|-------------|
| S520 (Preheating & Curing) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |
| S530 (Cooling) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |
| S540 (Robot) | LLM 색상 감지 전용 (3D 레이아웃 + wrong screen 체크) | RED/BLACK 스테이션 배경 | 장비 ID 미식별 또는 wrong screen |
| S510 (Robot 1) | LLM 색상 감지 전용 (RED 영역 감지) | RED 영역 감지 | 장비 ID 미식별 |
| S310 (Hairpin Insertion) | LLM 색상 감지 전용 (RED 영역 감지) | RED 영역 감지 | 장비 ID 미식별 |
| S810 (Housing Cooling) | DI 숫자 추출 + LLM 색상 감지 | 숫자 값 >= 3500 또는 RED 영역 감지 | 장비 ID 미식별 |

> 숫자 NG 임계값 기본값: 3500 (환경변수 `NUMERIC_NG_THRESHOLD`로 변경 가능)
> S540 wait count NG 임계값 기본값: 1200 (환경변수 `S540_WAIT_NG_THRESHOLD`로 변경 가능)

- **OK**: NG 조건 없음
- **NG**: 임계값 초과 또는 RED 영역 감지
- **UNKNOWN**: 장비 미식별, S540 wrong screen, 또는 DI 추출 실패

## Data Storage

```
data/
├── results/          # JSON 판정 결과 (debug 모드에서만 저장)
├─�