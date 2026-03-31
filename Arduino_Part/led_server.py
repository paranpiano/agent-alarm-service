from flask import Flask, request
import serial
import time
import threading

app = Flask(__name__)

# Arduino 연결 (COM 포트는 실제 환경에 맞게 변경)
ser = serial.Serial('COM4', 9600, timeout=1)
time.sleep(2)

# 타임아웃 설정
last_signal_time = time.time()
timeout_seconds = 40

def send_color(r, g, b):
    """Arduino로 RGB 값 전송"""
    ser.write(bytes([r, g, b]))

def check_timeout():
    """30초 동안 신호 없으면 LED 끄기"""
    global last_signal_time
    while True:
        time.sleep(5)  # 5초마다 체크
        if time.time() - last_signal_time > timeout_seconds:
            send_color(0, 0, 0)  # LED 끄기
            last_signal_time = time.time()

# 타임아웃 체크 쓰레드 시작
threading.Thread(target=check_timeout, daemon=True).start()

@app.route('/status', methods=['POST'])
def update_status():
    """상태에 따라 LED 색상 변경"""
    global last_signal_time
    last_signal_time = time.time()  # 신호 받은 시간 업데이트
    
    data = request.json
    status = data.get('status', '')
    
    if status == 'normal':
        send_color(0, 255, 0)  # 초록
        return {'result': 'Green LED ON'}, 200
    elif status == 'warning':
        send_color(255, 200, 0)  # 노랑
        return {'result': 'Yellow LED ON'}, 200
    elif status == 'ng':
        send_color(255, 0, 0)  # 빨강
        return {'result': 'Red LED ON'}, 200
    elif status == 'off':
        send_color(0, 0, 0)  # 끄기
        return {'result': 'LED OFF'}, 200
    else:
        return {'error': 'Invalid status'}, 400

@app.route('/color', methods=['POST'])
def set_color():
    """RGB 값 직접 제어"""
    global last_signal_time
    last_signal_time = time.time()
    
    data = request.json
    r = data.get('r', 0)
    g = data.get('g', 0)
    b = data.get('b', 0)
    
    # RGB 값 범위 체크 (0-255)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    
    send_color(r, g, b)
    return {'result': f'RGB({r},{g},{b})'}, 200

if __name__ == '__main__':
    print("LED Control Server Starting...")
    print("Server running on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000)
