# AI Alarm System — HTTP API Reference

서버에 HTTP 요청을 보내는 방법을 설명합니다.
언어나 프레임워크에 관계없이 `multipart/form-data`를 지원하는 HTTP 클라이언트라면 모두 사용할 수 있습니다.

---

## 기본 정보

| 항목 | 값 |
|------|-----|
| Base URL | `http://{host}:8000` |
| 기본 포트 | `8000` |
| 인증 | 없음 |
| 요청 형식 | `multipart/form-data` |
| 응답 형식 | `application/json` |

---

## 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/v1/analyze` | HMI 이미지 분석 |
| `GET` | `/api/v1/health` | 서버 상태 확인 |

---

## POST /api/v1/analyze

HMI 패널 이미지를 분석하여 장비 상태(OK / NG / UNKNOWN / TIMEOUT)를 반환합니다.

### 요청

```
POST /api/v1/analyze
Content-Type: multipart/form-data
```

**Form 필드**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `image` | file | 필수 | PNG 또는 JPEG 이미지. 최대 20MB |
| `request_id` | string | 선택 | 요청 식별자. 미입력 시 서버가 자동 생성 (`req_YYYYMMDD_HHMMSS_XXXX`) |
| `mode` | string | 선택 | `auto` (기본값) / `single_panel` / `4panel` |

**mode 설명**

| 값 | 동작 |
|----|------|
| `auto` | 이미지 픽셀 수로 자동 판단 (권장). 1,000,000px 미만이면 단일 패널로 처리 |
| `single_panel` | 단일 패널 크롭 이미지임을 강제 지정 |
| `4panel` (그 외 값) | 전체 4-panel HMI 이미지로 강제 지정 |

**이미지 규격**

| 구분 | 해상도 | 설명 |
|------|--------|------|
| 전체 HMI | 1920 × 1170 | 4개 패널이 포함된 전체 화면 캡처 |
| 단일 패널 | 960 × 585 | 패널 1개만 크롭한 이미지 |

---

### 성공 응답

**HTTP 200**

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

---

### 응답 필드 설명

**최상위 필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| `request_id` | string | 요청 식별자 |
| `status` | string | 판정 결과. `OK` / `NG` / `UNKNOWN` / `TIMEOUT` |
| `reason` | string | 판정 이유 (한국어) |
| `timestamp` | string | 분석 완료 시각 (ISO 8601, 로컬 시간) |
| `processing_time_ms` | integer | 서버 처리 시간 (밀리초) |
| `image_name` | string | 업로드된 이미지 파일명 |
| `equipment_data` | object \| null | 장비별 상세 분석 결과 |

**status 값**

| 값 | 의미 |
|----|------|
| `OK` | 모든 장비 정상 |
| `NG` | 이상 감지 (임계값 초과 또는 RED 영역 발견) |
| `UNKNOWN` | 판단 불가 (장비 미식별, 화면 가림/조작 의심, S540 비정상 화면) |
| `TIMEOUT` | LLM 응답 시간 초과 (30초) |

**equipment_data 장비별 필드**

장비 ID는 `S520`, `S530`, `S540`, `S810` 네 가지입니다.

| 필드 | 타입 | 대상 장비 | 설명 |
|------|------|----------|------|
| `identified` | boolean | 전체 | 장비 패널 식별 성공 여부 |
| `curing_oven` | integer[] | S520 | Curing Oven 수치값 목록 (최대 14개) |
| `preheating_oven` | integer[] | S520 | Preheating Oven 수치값 목록 (최대 14개) |
| `cooling_1_line` | integer[] | S530, S810 | Cooling 1 Line 수치값 목록 (S530 최대 14개, S810 최대 15개) |
| `cooling_2_line` | integer[] | S530, S810 | Cooling 2 Line 수치값 목록 (S530 최대 14개, S810 최대 15개) |
| `color_reasoning` | string | 전체 | LLM 색상 감지 판단 근거 |
| `ng_items` | string[] | 전체 | NG 항목 목록. 정상이면 빈 배열 `[]` |

**ng_items 패턴**

| 예시 | 의미 |
|------|------|
| `"curing_oven: 3200 (>= 3000)"` | 수치값이 임계값(3000) 이상 |
| `"RED [center, station label '6-1']: 6-1"` | 빨간 배경 영역 감지 |

---

### 에러 응답

**HTTP 400 / 500**

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

**에러 코드**

| code | HTTP | 발생 조건 |
|------|------|----------|
| `MISSING_IMAGE` | 400 | `image` 필드가 요청에 없음 |
| `INVALID_IMAGE_FORMAT` | 400 | PNG/JPEG 이외 형식 또는 손상된 파일 |
| `IMAGE_TOO_LARGE` | 400 | 파일 크기 20MB 초과 |
| `LLM_SERVICE_ERROR` | 500 | 서버 내부 분석 오류 |

---

## GET /api/v1/health

서버 가동 상태를 확인합니다.

### 요청

```
GET /api/v1/health
```

### 응답

**HTTP 200**

```json
{
    "status": "healthy",
    "timestamp": "2026-03-26T14:31:13"
}
```

---

## 코드 예제

### Python (requests)

```python
import requests

url = "http://localhost:8000/api/v1/analyze"

with open("hmi_screenshot.png", "rb") as f:
    response = requests.post(
        url,
        files={"image": ("hmi_screenshot.png", f, "image/png")},
        data={"request_id": "my-req-001"},
        timeout=35,
    )

response.raise_for_status()
data = response.json()

print(data["status"])   # "OK" | "NG" | "UNKNOWN" | "TIMEOUT"
print(data["reason"])
print(data["processing_time_ms"], "ms")
```

### C# (HttpClient)

```csharp
using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(35) };

using var form = new MultipartFormDataContent();
var imageBytes = await File.ReadAllBytesAsync("hmi_screenshot.png");
form.Add(new ByteArrayContent(imageBytes), "image", "hmi_screenshot.png");
form.Add(new StringContent("my-req-001"), "request_id");

var response = await client.PostAsync("http://localhost:8000/api/v1/analyze", form);
response.EnsureSuccessStatusCode();

var json = await response.Content.ReadAsStringAsync();
// json 파싱은 System.Text.Json 또는 Newtonsoft.Json 사용
```

### curl

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -F "image=@hmi_screenshot.png" \
  -F "request_id=my-req-001"
```

---

## 타임아웃 권장값

서버의 LLM 처리 시간은 이미지에 따라 7~15초 소요됩니다.
클라이언트 타임아웃은 **35초 이상**으로 설정하는 것을 권장합니다.

| 설정 | 권장값 |
|------|--------|
| 클라이언트 HTTP 타임아웃 | 35초 이상 |
| 서버 LLM 타임아웃 | 30초 (고정) |
| 재시도 간격 | 즉시 재시도 (최대 3회) |
