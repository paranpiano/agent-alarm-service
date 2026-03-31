# LED 램프 제어 시스템

Arduino와 WS2815 LED 스트립을 사용한 생산 모니터링 시스템

## 필요한 것
- Arduino Uno R4 WiFi (또는 R3 호환 보드)
- WS2815 12V LED 스트립 (300개)
- 12V 5A 어댑터
- 듀폰 점퍼선 (수-수)
- Python 3.7 이상

## 하드웨어 연결
1. LED 굵은 빨강 → 12V 어댑터 +
2. LED 굵은 검정 → 12V 어댑터 -
3. LED 커넥터 초록(DATA) → Arduino D6
4. LED 커넥터 흰색(GND) → Arduino GND
5. **주의: 커넥터 빨강, 파랑은 연결하지 마세요!**

## 소프트웨어 설치

### 1. Arduino IDE
1. Arduino IDE 실행
2. `led_control.ino` 파일 열기
3. 보드: Arduino Uno R4 WiFi (또는 R3) 선택
4. 포트 선택 (예: COM4)
5. 업로드

### 2. Python 라이브러리 설치
```bash
pip install flask pyserial
```

### 3. COM 포트 수정
`led_server.py` 파일에서:
```python
ser = serial.Serial('COM4', 9600, timeout=1)  # COM4를 실제 포트로 변경
```

## 사용법

### 1. Python 서버 실행
```bash
python led_server.py
```

### 2. API 호출

**정상 (초록)**
```python
import requests
requests.post('http://localhost:5000/status', json={'status': 'normal'})
```

**경고 (노랑)**
```python
requests.post('http://localhost:5000/status', json={'status': 'warning'})
```

**에러 (빨강)**
```python
requests.post('http://localhost:5000/status', json={'status': 'ng'})
```

**끄기**
```python
requests.post('http://localhost:5000/status', json={'status': 'off'})
```

**RGB 직접 제어**
```python
requests.post('http://localhost:5000/color', json={'r': 255, 'g': 100, 'b': 0})
```

## 특징
- 30초 동안 신호 없으면 자동으로 LED 꺼짐
- RGB 색상 자유롭게 제어 가능
- Flask API로 원격 제어 가능

## 문제 해결
- LED가 안 켜지면: DATA 선(초록) 연결 확인
- 포트 오류: 장치 관리자에서 실제 COM 포트 확인
- 노란색이 이상하면: `led_control.ino`에서 RGB 값 조정
