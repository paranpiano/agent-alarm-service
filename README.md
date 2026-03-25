# AI Alarm System (POC)

HMI 패널 이미지를 Azure OpenAI Vision API로 분석하여 제조 장비 상태를 자동 판단하는 시스템.

## Architecture

```
Client (tkinter GUI)  →  Server (Flask)  →  Azure OpenAI GPT-4o Vision
     Mock Tester           REST API            LangChain AzureChatOpenAI
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12.9 |
| Server | Flask + waitress (Windows) |
| LLM | Azure OpenAI GPT-4o Vision via `langchain-openai` |
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
│   ├── prompt_config.yaml       # LLM prompt & judgment criteria
│   ├── server_config.yaml       # Server settings
│   ├── .env.example             # Azure credentials template
│   ├── api/
│   │   └── routes.py            # Flask API routes
│   └── services/
│       ├── llm_service.py       # Azure OpenAI Vision integration
│       ├── image_validator.py   # PNG/JPEG validation
│       └── email_notifier.py    # UNKNOWN status email alerts
├── client/
│   ├── main.py                  # GUI entry point
│   ├── gui.py                   # tkinter Mock Tester GUI
│   ├── api_client.py            # HTTP client (retry 3x)
│   ├── periodic_runner.py       # Periodic request runner (5s/10s)
│   └── models.py                # Re-exported data models
├── test_images/
│   ├── ok/                      # Expected OK images
│   ├── ng/                      # Expected NG images
│   └── unknown/                 # Expected UNKNOWN images
├── tests/
│   ├── unit/                    # 171 unit tests
│   └── property/                # Property-based tests (optional)
└── requirements.txt
```

## Quick Start

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 2. Configure Azure OpenAI

```bash
cp server/.env.example server/.env
# Edit server/.env with your Azure OpenAI credentials
```

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
API_VERSION=2024-12-01-preview
VISION_MODEL=gpt-4o-korea-rag
```

### 3. Start the server

```bash
# Development mode
python -m server.main --dev

# Production mode (waitress)
python -m server.main
```

### 4. Start the client GUI

```bash
python -m client.main
```

### 5. Test

1. Click "Browse Folder..." and select the `test_images/` directory
2. Click "Analyze All" to send all images for analysis
3. Check the results table for OK/NG/UNKNOWN/TIMEOUT status
4. Use "Start Periodic" for continuous monitoring (5s or 10s interval)

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
  "reason": "All equipment normal.",
  "timestamp": "2024-01-01T12:00:00Z",
  "processing_time_ms": 1523,
  "equipment_data": { ... }
}
```

Status values: `OK`, `NG`, `UNKNOWN`, `TIMEOUT`

## Equipment & Judgment Criteria

4 equipment panels are analyzed from a single HMI screenshot:

| Equipment | Data Points | NG Condition |
|-----------|------------|--------------|
| S520 (Preheating & Curing) | 28 values (white row) | Any value >= 3000 |
| S530 (Cooling) | 28 values (white row) | Any value >= 3000 |
| S540 (Robot) | 12 stations (1-1 ~ 6-2) | Red or black background |
| S810 (Housing Cooling) | 30 values (white row) | Any value >= 3000 |

- **OK**: All data extracted, no NG conditions
- **NG**: Any threshold exceeded or abnormal station color
- **UNKNOWN**: Equipment not identified or data extraction incomplete

## Configuration

- `server/prompt_config.yaml` — LLM prompt, equipment definitions, judgment criteria
- `server/server_config.yaml` — Host, port, timeout, email, storage paths
- `server/.env` — Azure OpenAI credentials (gitignored)

## Running Tests

```bash
python -m pytest tests/ -v
```

## Data Storage

```
data/
├── results/          # JSON judgment results per request
├── logs/             # Daily log files (YYYY-MM-DD.log)
└── unknown_images/   # Saved images for UNKNOWN judgments
```
