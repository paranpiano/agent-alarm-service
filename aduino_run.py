from flask import Flask, request
import serial
import time
import threading

app = Flask(__name__)

ser = serial.Serial('COM3', 9600, timeout=1)
time.sleep(2)

last_signal_time = time.time()
timeout_seconds = 30

def send_color(r, g, b):
    """RGB 값 전송"""
    ser.write(bytes([r, g, b]))

def check_timeout():
    global last_signal_time
    while True:
        time.sleep(5)
        if time.time() - last_signal_time > timeout_seconds:
            send_color(0, 0, 0)  # 끄기
            last_signal_time = time.time()

threading.Thread(target=check_timeout, daemon=True).start()

@app.route('/status', methods=['POST'])
def update_status():
    global last_signal_time
    last_signal_time = time.time()
    
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

# RGB 직접 제어 API 추가
@app.route('/color', methods=['POST'])
def set_color():
    global last_signal_time
    last_signal_time = time.time()
    
    data = request.json
    r = data.get('r', 0)
    g = data.get('g', 0)
    b = data.get('b', 0)
    
    send_color(r, g, b)
    return {'result': f'RGB({r},{g},{b})'}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)