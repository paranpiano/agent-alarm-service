# 요구사항 문서

## 소개

AI Agent 기반 Alarm 시스템은 Client가 화면을 캡처하여 Server로 전송하면, Server가 Azure OpenAI LLM을 활용하여 화면 상태를 분석하고 판단 결과를 Client에 반환하는 시스템이다. 판단 결과는 OK, NG, 또는 예상하지 못한 상황으로 분류되며, 알 수 없는 상황 발생 시 이메일 알림을 전송한다. RPA와 AI Agent Service를 연동하여 자동화된 모니터링 및 알람 기능을 제공한다.

## 용어 정의

- **Client**: 화면 캡처 및 Server와 통신하는 Python 프로그램
- **Server**: Client로부터 이미지를 수신하고 LLM에 분석을 요청하며 결과를 반환하는 Python 백엔드 서비스
- **LLM_Service**: Azure OpenAI API를 통해 이미지와 프롬프트를 분석하는 AI 서비스
- **Judgment_Result**: LLM이 이미지를 분석한 결과를 담는 JSON 형식의 데이터 구조
- **OK_Status**: 화면 상태가 정상으로 판단된 경우
- **NG_Status**: 화면 상태가 비정상으로 판단된 경우
- **Unknown_Status**: LLM이 기존 조건으로 판단할 수 없는 예상하지 못한 상황
- **Prompt_Config**: LLM에 전달할 판단 조건과 지시사항을 정의한 설정
- **Email_Notifier**: 알 수 없는 상황 발생 시 AWS SNS API Gateway를 통해 알림을 전송하는 모듈 (클래스명은 하위 호환성 유지)
- **Judgment_Log**: 판단 이유, 타임스탬프, 결과를 포함하는 로그 기록

## 요구사항

### 요구사항 1: 화면 캡처

**사용자 스토리:** RPA 운영자로서, Client가 현재 화면을 캡처하여 분석용 이미지를 생성할 수 있기를 원한다. 이를 통해 화면 상태를 자동으로 모니터링할 수 있다.

#### 인수 조건

1. WHEN 캡처 요청이 발생하면, THE Client SHALL 현재 화면을 이미지 파일로 캡처한다
2. THE Client SHALL 캡처한 이미지를 PNG 또는 JPEG 형식으로 생성한다
3. IF 화면 캡처에 실패하면, THEN THE Client SHALL 오류 메시지와 타임스탬프를 로그에 기록한다

### 요구사항 2: 이미지 전송

**사용자 스토리:** RPA 운영자로서, Client가 캡처한 이미지를 Server에 전송할 수 있기를 원한다. 이를 통해 Server가 이미지를 분석할 수 있다.

#### 인수 조건

1. WHEN 이미지 캡처가 완료되면, THE Client SHALL 캡처한 이미지를 HTTP 요청으로 Server에 전송한다
2. THE Client SHALL 이미지 전송 시 타임스탬프와 요청 식별자를 함께 전송한다
3. IF 이미지 전송에 실패하면, THEN THE Client SHALL 재시도를 최대 3회 수행한다
4. IF 재시도 3회 후에도 전송에 실패하면, THEN THE Client SHALL 전송 실패 오류를 로그에 기록한다

### 요구사항 3: Server 이미지 수신

**사용자 스토리:** 시스템 관리자로서, Server가 Client로부터 이미지를 수신하고 유효성을 검증할 수 있기를 원한다. 이를 통해 올바른 이미지만 LLM에 전달할 수 있다.

#### 인수 조건

1. WHEN Client로부터 이미지 요청이 수신되면, THE Server SHALL 이미지 데이터와 메타데이터를 수신한다
2. WHEN 이미지가 수신되면, THE Server SHALL 이미지 형식이 PNG 또는 JPEG인지 검증한다
3. IF 유효하지 않은 이미지 형식이 수신되면, THEN THE Server SHALL 오류 응답 코드와 오류 메시지를 Client에 반환한다

### 요구사항 4: LLM 분석 요청

**사용자 스토리:** 시스템 관리자로서, Server가 수신한 이미지를 Azure OpenAI LLM에 전달하여 화면 상태를 분석할 수 있기를 원한다. 이를 통해 AI 기반 자동 판단이 가능하다.

#### 인수 조건

1. WHEN 유효한 이미지가 수신되면, THE Server SHALL 이미지와 Prompt_Config를 LLM_Service에 전달한다
2. THE Server SHALL Prompt_Config에 정의된 판단 조건(OK, NG, Unknown 기준)을 LLM_Service 요청에 포함한다
3. THE Server SHALL LLM_Service 요청 시 응답 형식을 JSON으로 지정한다
4. IF LLM_Service 호출에 실패하면, THEN THE Server SHALL 오류 내용을 로그에 기록하고 Client에 오류 응답을 반환한다

### 요구사항 5: 프롬프트 설정 관리

**사용자 스토리:** 시스템 관리자로서, LLM에 전달할 판단 조건을 외부 설정 파일로 관리할 수 있기를 원한다. 이를 통해 코드 변경 없이 판단 기준을 수정할 수 있다.

#### 인수 조건

1. THE Server SHALL Prompt_Config를 외부 설정 파일(JSON 또는 YAML)에서 로드한다
2. WHEN Server가 시작되면, THE Server SHALL Prompt_Config 파일의 존재 여부와 형식을 검증한다
3. IF Prompt_Config 파일이 존재하지 않거나 형식이 올바르지 않으면, THEN THE Server SHALL 오류 메시지를 로그에 기록하고 시작을 중단한다

### 요구사항 6: 판단 결과 파싱

**사용자 스토리:** 시스템 관리자로서, Server가 LLM의 JSON 응답을 파싱하여 구조화된 Judgment_Result를 생성할 수 있기를 원한다. 이를 통해 결과를 일관되게 처리할 수 있다.

#### 인수 조건

1. WHEN LLM_Service로부터 응답이 수신되면, THE Server SHALL JSON 응답을 Judgment_Result 객체로 파싱한다
2. THE Judgment_Result SHALL 판단 상태(OK_Status, NG_Status, Unknown_Status), 판단 이유, 타임스탬프를 포함한다
3. IF LLM_Service 응답이 유효한 JSON 형식이 아니면, THEN THE Server SHALL 파싱 오류를 로그에 기록하고 해당 요청을 Unknown_Status로 처리한다
4. THE Server SHALL Judgment_Result를 JSON 형식으로 직렬화하여 저장할 수 있다
5. FOR ALL 유효한 Judgment_Result 객체에 대해, 직렬화 후 역직렬화하면 원본과 동일한 객체가 생성된다 (라운드트립 속성)

### 요구사항 7: 판단 결과 및 로그 저장

**사용자 스토리:** 시스템 관리자로서, 모든 판단 결과와 판단 이유를 저장할 수 있기를 원한다. 이를 통해 이후 분석과 감사에 활용할 수 있다.

#### 인수 조건

1. WHEN Judgment_Result가 생성되면, THE Server SHALL 판단 결과를 JSON 파일로 저장한다
2. THE Server SHALL 각 판단에 대해 판단 이유, 타임스탬프, 요청 식별자를 Judgment_Log에 기록한다
3. WHEN Unknown_Status 판단이 발생하면, THE Server SHALL 해당 분석 대상 이미지를 별도 디렉토리에 저장한다
4. THE Server SHALL 저장된 JSON 파일과 로그 파일에 요청 식별자를 기준으로 접근할 수 있다

### 요구사항 8: SNS 알림

**사용자 스토리:** 시스템 관리자로서, 예상하지 못한 상황이 발생하면 알림을 받을 수 있기를 원한다. 이를 통해 신속하게 대응할 수 있다.

#### 인수 조건

1. WHEN Unknown_Status 판단이 발생하면, THE Email_Notifier SHALL AWS SNS API Gateway를 통해 지정된 수신자에게 알림을 전송한다
2. THE Email_Notifier SHALL 알림에 판단 이유, 타임스탬프, 요청 식별자를 포함한다
3. IF 알림 전송에 실패하면, THEN THE Email_Notifier SHALL 전송 실패를 로그에 기록하고 재시도를 최대 3회 수행한다
4. THE Email_Notifier SHALL SNS 설정(api_url, topic_arn)을 외부 환경 변수에서 로드한다
5. IF SNS_ENABLED=false이면, THEN THE Email_Notifier SHALL 알림 전송을 건너뛰고 로그에 기록한다

### 요구사항 10: S540 화면 모드 감지

**사용자 스토리:** 시스템 관리자로서, S540 패널이 정상 화면이 아닌 다른 메뉴를 표시할 때 이를 감지하여 UNKNOWN으로 처리할 수 있기를 원한다.

#### 인수 조건

1. WHEN S540 패널이 정상 3D 스테이션 레이아웃이 아닌 화면(Setup & Parameters, Machine Parameter 등)을 표시하면, THE Server SHALL 해당 요청을 Unknown_Status로 처리한다
2. THE Server SHALL S540 wrong screen 감지 시 이메일 알림을 발송한다
3. THE Server SHALL wrong screen 여부를 LLM 색상 감지 응답의 `wrong_screen` 필드로 판단한다

### 요구사항 9: 판단 결과 Client 반환

**사용자 스토리:** RPA 운영자로서, Server로부터 판단 결과를 수신하여 후속 작업을 수행할 수 있기를 원한다. 이를 통해 RPA 프로세스와 연동할 수 있다.

#### 인수 조건

1. WHEN Judgment_Result가 생성되면, THE Server SHALL Judgment_Result를 JSON 형식으로 Client에 HTTP 응답으로 반환한다
2. THE Server SHALL 응답에 판단 상태, 판단 이유, 타임스탬프, 요청 식별자를 포함한다
3. WHEN Client가 응답을 수신하면, THE Client SHALL Judgment_Result를 파싱하여 판단 상태를 확인한다
4. IF Server 응답이 유효한 JSON 형식이 아니면, THEN THE Client SHALL 파싱 오류를 로그에 기록한다
