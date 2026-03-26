# AI Alarm System — Python Client API 문서

외부 Python 코드에서 AI Alarm System 서버와 통신하는 방법을 설명합니다.
`AlarmApiClient`를 직접 사용하거나, HTTP를 직접 호출하는 두 가지 방법을 모두 다룹니다.

---

## 목차

1. [빠른 시작](#1-빠른-시작)
2. [AlarmApiClient 클래스](#2-alarmapiclient-클래스)
3. [데이터 모델](#3-데이터-모델)
4. [HTTP API 직접 호출](#4-http-api-직접-호출)
5. [에러 처리](#5-에러-처리)
6. [사용 예제](#6-사용-예제)

---

## 1. 빠른 시작

```python
from pathlib import Path
from client.api_client import AlarmApiClient

client = AlarmApiClient(base_url="http://localhost:8000")

result = client.analyze_single(Path("screenshot.png"))
print(result.status)   # "OK" | "NG" | "UNKNOWN" | "TIMEOUT"
print(result.reason)   # 판단 이유 (한국어)
```

---

## 2. AlarmApiClient 클래스

```python
from client.api_client import AlarmApiClient
```

### 생성자

```python
AlarmApiClient(base_url: str, request_timeout: float = 35.0)
```

| 파라미터 | 타입 | 기본값 | 설명 |
|---------|------|--------|------|
| `base_url` | `str` | — | 서버 주소 (예: `http://localhost:8000`) |
| `request_timeout` | `float` | `35.0` | HTTP 요청 타임아웃 (초). 서버 LLM 타임아웃(30s)보다 약간 길게 설정 |

```python
client = AlarmApiClient("http://localhost:8000")
client = AlarmApiClient("http://192.168.1.100:8000", request_timeout=60.0)
```

---

### `analyze_single(image_path)`

단일 이미지를 서버에 전송하여 분석 결과를 반환합니다.
네트워크 오류 시 최대 3회 자동 재시도합니다.

```python
def analyze_single(image_path: Path) -> JudgmentResult
```

**파라미터**

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `image_path` | `pathlib.Path` | 분석할 이미지 파일 경로 (PNG 또는 JPEG) |

**반환값**: [`JudgmentResult`](#judgmentresult)

**예외**

| 예외 | 발생 조건 |
|------|----------|
| `FileNotFoundError` | 이미지 파일이 존재하지 않을 때 |
| `requests.ConnectionError` | 3회 재시도 후에도 서버 연결 실패 |
| `requests.Timeout` | 3회 재시도 후에도 타임아웃 |
| `ValueError` | 서버 응답이 유효한 JSON이 아닐 때 |

**패널 자동 감지**

서버는 이미지 픽셀 수를 기준으로 자동으로 모드를 결정합니다:
- 전체 HMI 이미지 (1920×1170, ~2.25M px) → 4-panel 모드
- 단일 패널 크롭 (960×585, ~0.56M px) → single-panel 모드
- 기준: 총 픽셀 수 < 1,000,000 → single panel

```python
from pathlib import Path
from client.api_client import AlarmApiClient

client = AlarmApiClient("http://localhost:8000")

# 전체 HMI 이미지 (4패널 자동 분석)
result = client.analyze_single(Path("hmi_full.png"))

# 단일 패널 크롭 이미지 (자동 감지)
result = client.analyze_single(Path("s540_panel.png"))
```

---

### `health_check()`

서버 상태를 확인합니다.

```python
def health_check() -> bool
```

**반환값**: 서버가 정상이면 `True`, 응답 없거나 오류면 `False`

```python
if client.health_check():
    result = client.analyze_single(image_path)
else:
    print("서버에 연결할 수 없습니다.")
```

---

## 3. 데이터 모델

```python
from client.models import JudgmentResult, JudgmentStatus
# 또는
from server.models import JudgmentResult, JudgmentStatus
```

### JudgmentStatus

```python
class JudgmentStatus(str, Enum):
    OK      = "OK"       # 모든 장비 정상
    NG      = "NG"       # 이상 감지 (임계값 초과 또는 RED 영역)
    UNKNOWN = "UNKNOWN"  # 판단 불가 (장비 미식별, 화면 가림 등)
    TIMEOUT = "TIMEOUT"  # LLM 응답 시간 초과 (30초)
```

`JudgmentStatus`는 `str`을 상속하므로 문자열과 직접 비교 가능합니다:

```python
result.status == "OK"                    # True
result.status == JudgmentStatus.OK       # True
result.status.value                      # "OK"
```

---

### JudgmentResult

분석 결과를 담는 데이터 클래스입니다.

```python
@dataclass
class JudgmentResult:
    request_id:         str                      # 요청 고유 ID (req_YYYYMMDD_HHMMSS_XXXX)
    status:             JudgmentStatus           # OK | NG | UNKNOWN | TIMEOUT
    reason:             str                      # 판단 이유 (한국어)
    timestamp:          str                      # ISO 8601 로컬 시각 (YYYY-MM-DDTHH:MM:SS)
    processing_time_ms: int                      # 처리 시간 (밀리초)
    image_name:         str                      # 분석한 이미지 파일명
    equipment_data:     dict[str, Any] | None    # 장비별 상세 데이터 (아래 참조)
```

**equipment_data 구조**

`equipment_data`는 S520, S530, S540, S810 네 장비의 분석 결과를 담습니다.

```python
{
    "S520": {
        "identified": True,
        "curing_oven":      [2887, 2767, 2801, ...],   # 숫자 추출값 리스트 (최대 14개)
        "preheating_oven":  [1388, 1402, 1390, ...],   # 숫자 추출값 리스트 (최대 14개)
        "color_reasoning":  "No red areas detected.",
        "ng_items":         []                          # NG 항목 리스트 (비어있으면 정상)
    },
    "S530": {
        "identified": True,
        "cooling_1_line":   [1200, 1350, ...],          # 숫자 추출값 (최대 14개)
        "cooling_2_line":   [1100, 1280, ...],          # 숫자 추출값 (최대 14개)
        "color_reasoning":  "No red areas detected.",
        "ng_items":         []
    },
    "S540": {
        "identified": True,
        "color_reasoning":  "Station 6-1 has red background.",
        "ng_items":         ["RED [center, station label '6-1']: 6-1"]
    },
    "S810": {
        "identified": True,
        "cooling_1_line":   [980, 1020, ...],           # 숫자 추출값 (최대 15개)
        "cooling_2_line":   [1050, 1100, ...],          # 숫자 추출값 (최대 15개)
        "color_reasoning":  "No red areas detected.",
        "ng_items":         []
    }
}
```

**ng_items 패턴**

| 패턴 | 의미 |
|------|------|
| `"curing_oven: 3200 (>= 3000)"` | 숫자 임계값 초과 |
| `"RED [위치]: 텍스트"` | 빨간 배경 영역 감지 |
| `"WRONG_SCREEN: ..."` | S540 비정상 화면 (UNKNOWN 처리) |

**직렬화 / 역직렬화**

```python
# dict로 변환
data = result.to_dict()

# dict에서 복원
result = JudgmentResult.from_dict(data)
```

---

## 4. HTTP API 직접 호출

`AlarmApiClient` 없이 `requests` 등으로 직접 호출할 때의 스펙입니다.

### POST /api/v1/analyze

이미지를 분석하여 판정 결과를 반환합니다.

**요청**

```
POST http://localhost:8000/api/v1/analyze
Content-Type: multipart/form-data
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `image` | file | 필수 | PNG 또는 JPEG 이미지 (최대 20MB) |
| `request_id` | string | 선택 | 클라이언트 지정 요청 ID. 미입력 시 서버가 자동 생성 |
| `mode` | string | 선택 | `"auto"` (기본값) / `"single_panel"` / `"4panel"` |

`mode` 상세:
- `auto`: 이미지 픽셀 수로 자동 판단 (권장)
- `single_panel`: 단일 패널 크롭 이미지임을 강제 지정
- 그 외: 4-panel 모드 강제 지정

**성공 응답** `HTTP 200`

```json
{
    "request_id": "req_20260326_143113_3243",
    "status": "OK",
    "reason": "모든 장비 정상입니다.",
    "timestamp": "2026-03-26T14:31:13",
    "processing_time_ms": 7842,
    "image_name": "hmi_screenshot.png",
    "equipment_data": {
        "S520": {
            "identified": true,
            "curing_oven": [2887, 2767, 2801, 2755, 2890, 2812, 2798, 2834, 2801, 2756, 2823, 2867, 2812, 2798],
            "preheating_oven": [1388, 1402, 1390, 1378, 1395, 1412, 1388, 1401, 1390, 1378, 1395, 1412, 1388, 1401],
            "color_reasoning": "No red areas detected in S520 panel.",
            "ng_items": []
        },
        "S530": {
            "identified": true,
            "cooling_1_line": [1200, 1350, 1280, 1310, 1290, 1320, 1300, 1280, 1310, 1290, 1320, 1300, 1280, 1310],
            "cooling_2_line": [1100, 1280, 1250, 1270, 1240, 1260, 1250, 1240, 1260, 1250, 1240, 1260, 1250, 1240],
            "color_reasoning": "No red areas detected in S530 panel.",
            "ng_items": []
        },
        "S540": {
            "identified": true,
            "color_reasoning": "All 12 stations show normal green background.",
            "ng_items": []
        },
        "S810": {
            "identified": true,
            "cooling_1_line": [980, 1020, 1010, 990, 1005, 1015, 1000, 990, 1005, 1015, 1000, 990, 1005, 1015, 1000],
            "cooling_2_line": [1050, 1100, 1080, 1060, 1075, 1090, 1070, 1060, 1075, 1090, 1070, 1060, 1075, 1090, 1070],
            "color_reasoning": "No red areas detected in S810 panel.",
            "ng_items": []
        }
    }
}
```

**에러 응답** `HTTP 400 / 500`

```json
{
    "error": {
        "code": "INVALID_IMAGE_FORMAT",
        "message": "Unsupported image format. Only PNG and JPEG are accepted.",
        "request_id": "req_20260326_143113_3243",
        "timestamp": "2026-03-26T14:31:13"
    }
}
```

| 에러 코드 | HTTP | 설명 |
|-----------|------|------|
| `MISSING_IMAGE` | 400 | `image` 필드 누락 |
| `INVALID_IMAGE_FORMAT` | 400 | PNG/JPEG 이외 형식 또는 손상된 파일 |
| `IMAGE_TOO_LARGE` | 400 | 파일 크기 20MB 초과 |
| `LLM_SERVICE_ERROR` | 500 | 분석 서비스 내부 오류 |

---

### GET /api/v1/health

서버 상태를 확인합니다.

**요청**

```
GET http://localhost:8000/api/v1/health
```

**응답** `HTTP 200`

```json
{
    "status": "healthy",
    "timestamp": "2026-03-26T14:31:13"
}
```

---

## 5. 에러 처리

### AlarmApiClient 사용 시

```python
import requests
from pathlib import Path
from client.api_client import AlarmApiClient
from client.models import JudgmentStatus

client = AlarmApiClient("http://localhost:8000")

try:
    result = client.analyze_single(Path("hmi.png"))

    if result.status == JudgmentStatus.OK:
        print("정상")
    elif result.status == JudgmentStatus.NG:
        print(f"이상 감지: {result.reason}")
        for eq_id, eq_data in (result.equipment_data or {}).items():
            if eq_data.get("ng_items"):
                print(f"  [{eq_id}] {eq_data['ng_items']}")
    elif result.status == JudgmentStatus.UNKNOWN:
        print(f"판단 불가: {result.reason}")
    elif result.status == JudgmentStatus.TIMEOUT:
        print("분석 시간 초과 — 재시도 필요")

except FileNotFoundError as e:
    print(f"이미지 파일 없음: {e}")
except requests.ConnectionError:
    print("서버 연결 실패 (3회 재시도 후)")
except requests.Timeout:
    print("요청 타임아웃 (3회 재시도 후)")
except ValueError as e:
    print(f"응답 파싱 실패: {e}")
```

### requests 직접 사용 시

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    files={"image": open("hmi.png", "rb")},
    data={"request_id": "my-req-001"},
    timeout=35,
)

if response.status_code == 200:
    data = response.json()
    print(data["status"], data["reason"])
else:
    error = response.json()["error"]
    print(f"[{error['code']}] {error['message']}")
```

---

## 6. 사용 예제

### 단건 분석

```python
from pathlib import Path
from client.api_client import AlarmApiClient
from client.models import JudgmentStatus

client = AlarmApiClient("http://localhost:8000")
result = client.analyze_single(Path("hmi_screenshot.png"))

print(f"상태: {result.status}")
print(f"이유: {result.reason}")
print(f"처리시간: {result.processing_time_ms}ms")
```

### 폴더 내 이미지 일괄 분석

```python
from pathlib import Path
from client.api_client import AlarmApiClient
from client.models import JudgmentStatus

client = AlarmApiClient("http://localhost:8000")
image_dir = Path("test_images")

results = {"OK": [], "NG": [], "UNKNOWN": [], "TIMEOUT": []}

for img_path in sorted(image_dir.glob("*.png")):
    try:
        result = client.analyze_single(img_path)
        results[result.status.value].append(img_path.name)
        print(f"[{result.status}] {img_path.name} ({result.processing_time_ms}ms)")
    except Exception as e:
        print(f"[ERROR] {img_path.name}: {e}")

print(f"\nOK: {len(results['OK'])}, NG: {len(results['NG'])}, "
      f"UNKNOWN: {len(results['UNKNOWN'])}, TIMEOUT: {len(results['TIMEOUT'])}")
```

### NG 항목 상세 출력

```python
from pathlib import Path
from client.api_client import AlarmApiClient
from client.models import JudgmentStatus

client = AlarmApiClient("http://localhost:8000")
result = client.analyze_single(Path("hmi_ng_sample.png"))

if result.status == JudgmentStatus.NG and result.equipment_data:
    for eq_id, eq_data in result.equipment_data.items():
        ng_items = eq_data.get("ng_items", [])
        if ng_items:
            print(f"\n[{eq_id}] NG 항목:")
            for item in ng_items:
                print(f"  - {item}")

            # 숫자 임계값 초과 항목만 필터링
            numeric_ng = [i for i in ng_items if ">= 3000" in i]
            color_ng   = [i for i in ng_items if i.startswith("RED")]
            print(f"  숫자 NG: {len(numeric_ng)}건, 색상 NG: {len(color_ng)}건")
```

### 서버 상태 확인 후 분석

```python
from pathlib import Path
from client.api_client import AlarmApiClient

client = AlarmApiClient("http://localhost:8000")

if not client.health_check():
    raise RuntimeError("서버가 응답하지 않습니다.")

result = client.analyze_single(Path("hmi.png"))
print(result.status)
```

### requests만 사용 (의존성 최소화)

```python
import requests
from pathlib import Path

def analyze_image(image_path: str, server_url: str = "http://localhost:8000") -> dict:
    with open(image_path, "rb") as f:
        response = requests.post(
            f"{server_url}/api/v1/analyze",
            files={"image": (Path(image_path).name, f, "image/png")},
            timeout=35,
        )
    response.raise_for_status()
    return response.json()

data = analyze_image("hmi_screenshot.png")
print(data["status"])   # "OK" | "NG" | "UNKNOWN" | "TIMEOUT"
print(data["reason"])
```
