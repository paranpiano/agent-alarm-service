# Cloud Logging Architecture

서버에서 판정 결과를 AWS에 저장하는 구조입니다.

---

## 아키텍처 개요

```
Flask Server (analyze)
    │
    ├── local: JudgmentLogger → data/logs/YYYY-MM-DD.log
    │
    └── cloud: CloudLogger (async) → API Gateway → Lambda → DynamoDB
```

---

## AWS 리소스

| 리소스 | 이름 | 비고 |
|--------|------|------|
| API Gateway | ai-alarm-log-api | EDGE 타입 |
| Lambda | ai-alarm-log-manager | Python 3.12 |
| DynamoDB | ai-alarm-logs | PAY_PER_REQUEST |
| IAM Role | ai-alarm-log-lambda-role | BasicExecution + DynamoDB |

### API Endpoint

```
https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs
```

---

## API 명세

### POST /logs — 로그 저장

**Request Body (JSON)**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| request_id | String | ✅ | 요청 고유 ID |
| timestamp | String | ✅ | ISO 8601 (예: 2026-03-31T12:00:00) |
| status | String | ✅ | OK / NG / UNKNOWN |
| reason | String | | 판정 이유 |
| image_name | String | | 이미지 파일명 |
| processing_time_ms | Number | | 처리 시간 (ms) |
| equipment_data | Object | | 장비별 분석 데이터 |

**Response**
```json
{
  "message": "Log saved",
  "request_id": "req_20260331_120000_0001",
  "log_date": "2026-03-31"
}
```

### GET /logs — 로그 조회

**Query Parameters**

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| date | | YYYY-MM-DD (기본값: 오늘) |
| request_id | | 특정 요청 조회 |
| limit | | 최대 건수 (기본값: 100) |

**Response**
```json
{
  "logs": [...],
  "count": 1,
  "date": "2026-03-31"
}
```

---

## DynamoDB 스키마

| 키 | 타입 | 설명 |
|----|------|------|
| log_date | String (PK) | YYYY-MM-DD |
| request_id | String (SK) | 요청 고유 ID |
| timestamp | String | ISO 8601 |
| status | String | OK / NG / UNKNOWN |
| reason | String | 판정 이유 |
| image_name | String | 이미지 파일명 |
| processing_time_ms | Number | 처리 시간 (ms) |
| equipment_data | Map | 장비별 분석 데이터 |

---

## 서버 코드 구조

### CloudLogger (`server/services/cloud_logger.py`)

- `log_async(result)`: 별도 daemon 스레드로 비동기 업로드
- 메인 응답 속도에 영향 없음
- 업로드 실패 시 WARNING 로그만 기록 (서버 동작에 영향 없음)

### 흐름 (`server/api/routes.py` → `analyze()`)

```
1. LLM 분석
2. JudgmentResult 생성
3. JudgmentLogger.log_judgment()  ← 로컬 파일 저장
4. CloudLogger.log_async()        ← 클라우드 비동기 업로드 (fire-and-forget)
5. EmailNotifier.send_alert()     ← UNKNOWN 시 알림
6. Response 반환
```

### 환경변수 (`.env`)

```
LOG_API_URL=https://04x5u7rq6e.execute-api.eu-central-1.amazonaws.com/prod/logs
```

`LOG_API_URL`이 비어있으면 CloudLogger가 생성되지 않아 로컬 전용으로 동작합니다.

---

## Lambda 배포

코드 수정 후 재배포 절차:

```powershell
# 1. zip 생성
Compress-Archive -Path lambda/log_manager/lambda_function.py -DestinationPath lambda/log_manager/function.zip -Force

# 2. Lambda 업데이트
aws lambda update-function-code --region eu-central-1 --function-name ai-alarm-log-manager --zip-file fileb://lambda/log_manager/function.zip

# 3. API Gateway 재배포 (통합 설정 변경 시에만 필요)
aws apigateway create-deployment --rest-api-id 04x5u7rq6e --region eu-central-1 --stage-name prod
```
