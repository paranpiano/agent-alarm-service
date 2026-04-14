# Cloud Log API 연동 가이드

다른 프로그램에서 동일한 DynamoDB 로그 테이블에 데이터를 기록하기 위한 API 명세입니다.  
Web 대시보드(`cloud_logging/web`)에서 정상적으로 조회·분석되려면 이 문서의 포맷을 정확히 따라야 합니다.

---

## 엔드포인트

```
POST https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs
```

| 항목 | 값 |
|------|-----|
| Method | `POST` |
| Content-Type | `application/json` |
| 인증 | 없음 (API Gateway Public) |

---

## 요청 Body

```json
{
  "request_id": "req_20260414_153000_1234",
  "timestamp": "2026-04-14T15:30:00.123456",
  "status": "NG",
  "reason": "S540 장비에서 wait_counts 이상 감지됨 (최대값: 1350)",
  "image_name": "00012345.png",
  "processing_time_ms": 2340,
  "equipment_data": {
    "S540": {
      "identified": true,
      "ng_items": ["wait_counts 초과: 1350 >= 1200"],
      "wait_counts": [1200, 1350, 980],
      "color_reasoning": "정상 범위 초과"
    },
    "S520": {
      "identified": true,
      "ng_items": [],
      "curing_oven": [210, 215, 212],
      "preheating_oven": [180, 182]
    }
  }
}
```

---

## 필드 명세

### 최상위 필드

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `request_id` | string | **필수** | 요청 고유 ID. 형식: `req_YYYYMMDD_HHMMSS_XXXX` |
| `timestamp` | string | **필수** | ISO 8601 형식. 예: `2026-04-14T15:30:00.123456` |
| `status` | string | **필수** | `"OK"` 또는 `"NG"` 만 허용 (`UNKNOWN`, `TIMEOUT` 은 Web에서 필터 불가) |
| `reason` | string | 권장 | 판정 이유 텍스트. 비워두면 빈 문자열 `""` |
| `image_name` | string | 권장 | 분석한 이미지 파일명. 예: `00012345.png` |
| `processing_time_ms` | integer | 권장 | 처리 소요 시간(ms). 미입력 시 `0` |
| `equipment_data` | object | 권장 | 장비별 분석 결과. 미입력 시 `{}` |

### `request_id` 생성 규칙

```
req_{YYYYMMDD}_{HHMMSS}_{4자리난수}
```

예시:
```
req_20260414_153000_7823
```

- 날짜·시간은 로컬 시간 기준
- 4자리 난수는 동시 요청 충돌 방지용
- **DynamoDB Sort Key**로 사용되므로 테이블 내에서 유일해야 함

### `timestamp` 형식

```
YYYY-MM-DDTHH:MM:SS.ffffff
```

- Python: `datetime.now().isoformat()`
- Lambda가 이 값에서 `log_date`(파티션 키)를 자동 추출함
- **UTC가 아닌 로컬 시간**을 사용해도 무방하나, 팀 내 일관성 유지 필요

### `status` 허용값

| 값 | 의미 | Web 필터 지원 |
|----|------|--------------|
| `"OK"` | 정상 판정 | ✅ |
| `"NG"` | 이상 감지 | ✅ |
| `"UNKNOWN"` | 판정 불가 | ❌ (필터에서 제외됨) |
| `"TIMEOUT"` | 타임아웃 | ❌ (필터에서 제외됨) |

> Web 대시보드는 `OK` / `NG` 만 처리합니다. 다른 값은 저장은 되지만 차트·필터에서 누락됩니다.

---

## `equipment_data` 구조

장비 ID를 키로 하는 객체입니다.

```json
{
  "<장비ID>": {
    "identified": true,
    "ng_items": ["항목1", "항목2"],
    "color_reasoning": "색상 판단 근거 텍스트",
    "curing_oven": [210, 215, 212],
    "preheating_oven": [180, 182],
    "cooling_1_line": [45, 47],
    "cooling_2_line": [43, 44],
    "wait_counts": [1200, 1350]
  }
}
```

### 장비 ID 목록 (Web 대시보드 기준)

| 장비 ID | 색상 |
|---------|------|
| `S310` | 노랑 |
| `S510` | 보라 |
| `S520` | 파랑 |
| `S530` | 초록 |
| `S540` | 주황 |
| `S810` | 빨강 |

> 이 ID 외의 장비를 추가해도 저장은 되지만, Web 대시보드 장비 필터 버튼에는 표시되지 않습니다.

### `equipment_data` 필드 상세

| 필드 | 타입 | 설명 |
|------|------|------|
| `identified` | boolean | 이미지에서 해당 장비가 식별되었는지 여부 |
| `ng_items` | string[] | NG 항목 설명 목록. 정상이면 빈 배열 `[]` |
| `color_reasoning` | string | (선택) 색상 기반 판단 근거 |
| `curing_oven` | number[] | (선택) 경화로 수치 배열 |
| `preheating_oven` | number[] | (선택) 예열로 수치 배열 |
| `cooling_1_line` | number[] | (선택) 냉각 1라인 수치 배열 |
| `cooling_2_line` | number[] | (선택) 냉각 2라인 수치 배열 |
| `wait_counts` | number[] | (선택) 대기 카운트 배열 |

> `ng_items`가 비어있으면 해당 장비는 OK로 간주됩니다.  
> 수치 배열 필드는 없어도 무방하며, 있을 경우 Web 상세 팝업에 표시됩니다.

---

## DynamoDB 저장 구조

Lambda가 수신한 body를 아래와 같이 변환하여 저장합니다.

| DynamoDB 속성 | 타입 | 출처 |
|--------------|------|------|
| `log_date` | String (PK) | `timestamp`에서 자동 추출 (`YYYY-MM-DD`) |
| `request_id` | String (SK) | 요청 body의 `request_id` |
| `timestamp` | String | 요청 body의 `timestamp` |
| `status` | String | 요청 body의 `status` |
| `reason` | String | 요청 body의 `reason` |
| `image_name` | String | 요청 body의 `image_name` |
| `processing_time_ms` | Number | 요청 body의 `processing_time_ms` |
| `equipment_data` | String | `equipment_data` 객체를 **JSON 문자열로 직렬화**하여 저장 |

> `equipment_data`는 DynamoDB에 JSON 문자열로 저장되며, GET 응답 시 자동으로 파싱됩니다.

---

## 응답

### 성공 (200)

```json
{
  "message": "Log saved",
  "request_id": "req_20260414_153000_1234",
  "log_date": "2026-04-14"
}
```

### 실패 (400)

```json
{
  "error": "Missing required field: request_id"
}
```

---

## 구현 예시

### Python

```python
import requests
from datetime import datetime
import random

LOG_API_URL = "https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs"

def send_log(
    status: str,          # "OK" or "NG"
    reason: str,
    image_name: str,
    processing_time_ms: int,
    equipment_data: dict,
) -> None:
    now = datetime.now()
    request_id = f"req_{now.strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"

    payload = {
        "request_id": request_id,
        "timestamp": now.isoformat(),
        "status": status,
        "reason": reason,
        "image_name": image_name,
        "processing_time_ms": processing_time_ms,
        "equipment_data": equipment_data,
    }

    resp = requests.post(
        LOG_API_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()


# 사용 예
send_log(
    status="NG",
    reason="S540 wait_counts 초과",
    image_name="00012345.png",
    processing_time_ms=1200,
    equipment_data={
        "S540": {
            "identified": True,
            "ng_items": ["wait_counts 초과: 1350 >= 1200"],
            "wait_counts": [1200, 1350, 980],
        },
        "S520": {
            "identified": True,
            "ng_items": [],
        },
    },
)
```

### curl

```bash
curl -X POST https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "req_20260414_153000_1234",
    "timestamp": "2026-04-14T15:30:00.123456",
    "status": "NG",
    "reason": "S540 이상 감지",
    "image_name": "00012345.png",
    "processing_time_ms": 1200,
    "equipment_data": {
      "S540": {
        "identified": true,
        "ng_items": ["wait_counts 초과"],
        "wait_counts": [1350]
      }
    }
  }'
```

---

## 주의사항

1. **`status`는 반드시 `"OK"` 또는 `"NG"`** — 다른 값은 Web 대시보드에서 필터링되지 않음
2. **`request_id` 중복 금지** — 같은 `log_date` + `request_id` 조합으로 재전송하면 기존 항목이 덮어써짐 (DynamoDB `put_item` 동작)
3. **`equipment_data`는 객체로 전송** — Lambda가 내부적으로 JSON 문자열로 변환하므로, 클라이언트에서 직접 문자열로 직렬화하지 말 것
4. **`timestamp` 파싱 실패 시** Lambda가 UTC 현재 시각으로 `log_date`를 설정함 — 날짜가 틀려질 수 있으므로 ISO 8601 형식 준수 필요
5. **장비 ID는 대소문자 구분** — `S540`과 `s540`은 다른 키로 저장됨
