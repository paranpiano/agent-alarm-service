import win32gui, win32ui, glob, cv2, os, ctypes
import time, winsound, threading, datetime, random
import numpy as np
import tkinter as tk
import requests, serial
import concurrent.futures
from PIL import Image, ImageTk

global open_windows
global Logging_path

# ser = serial.Serial('COM3', 9600, timeout=1)

Logging_path = os.path.join(os.getcwd(), "Error Log")

user32 = ctypes.windll.user32
open_windows = {}

playing_sound_threads = {}
stop_sound_events = {}

led_threads = {}
stop_led_events = {}

NG_hwnd = []
UNKNOWN_hwnd = []

root = tk.Tk()
root.withdraw()

def logging(text):
    global Logging_path
    os.makedirs(os.path.join(Logging_path, "Error Log"), exist_ok=True)
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(Logging_path, "Error Log", f"{now_str}.txt"), 'a', encoding='utf-8') as F:
        F.write(text)
        F.write('\n')

def LED_OK():
    global ser
    # ser.write(bytes([0, 255, 0]))

def loop_led_NG(flag):
    global ser, stop_led_events

    if flag not in stop_led_events:
        stop_led_events[flag] = threading.Event()

    event = stop_led_events[flag]

    while not event.is_set():
        # ser.write(bytes([255, 0, 0]))
        time.sleep(0.5)
        # ser.write(bytes([0, 0, 0]))
        time.sleep(0.5)

def loop_sound(flag, sound_path):
    global stop_sound_events

    if flag not in stop_sound_events:
        stop_sound_events[flag] = threading.Event()

    event = stop_sound_events[flag]

    while not event.is_set():
        try:
            play_sound(sound_path)
        except Exception as e:
            logging(str(e))
            pass
        time.sleep(7)

# Windows sound
def play_sound(sound_path):
    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

def enum_windows():
    win_list = []
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.strip():
                win_list.append([hwnd, title, win32gui.GetWindowRect(hwnd)])
    win32gui.EnumWindows(callback, None)
    return win_list

def capturing(hwnd):
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w = right - left
        h = bottom - top

        hwndDC = win32gui.GetWindowDC(hwnd)
        srcDC = win32ui.CreateDCFromHandle(hwndDC)
        memDC = srcDC.CreateCompatibleDC()

        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcDC, w, h)
        memDC.SelectObject(bmp)

        PW_RENDERFULLCONTENT = 2
        user32.PrintWindow(hwnd, memDC.GetSafeHdc(), PW_RENDERFULLCONTENT)

        bmpstr = bmp.GetBitmapBits(True)
        img = np.frombuffer(bmpstr, dtype=np.uint8).reshape((h, w, 4))
        img = img[:, :, :3]

        win32gui.DeleteObject(bmp.GetHandle())
        memDC.DeleteDC()
        srcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)

        return img

    except Exception as e:
        print(f"{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}: Capture error:", e)
        logging(str(e))
        return None

def send_http(img):
    url = "http://127.0.0.1:8000/api/v1/analyze"
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    name = f"hmi_{random.randint(1, 10000)}_{now_str}.png"

    ret, buf = cv2.imencode(".png", img)
    if not ret:
        return "UNKNOWN"

    files = {
        "image": (name, buf.tobytes(), "image/png")
    }
    data = {
        "request_id": f"req_{now_str}",
        "mode": "auto"
    }

    try:
        response = requests.post(url, files=files, data=data, timeout=35)
        response.raise_for_status()
        js = response.json()
        return js.get("status", "UNKNOWN")
    except Exception as e:
        logging(str(e))
        return "UNKNOWN"

def alarm_pop_up(flag, UI_Images, hwnd_list=None):
    global NG_hwnd, UNKNOWN_hwnd, open_windows
    
    print(f"{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}: {flag}")

    if flag == "OK":
        for f, event in stop_sound_events.items():
            try:
                event.set()
            except Exception as e:
                logging(str(e))
                pass
        stop_sound_events.clear()
        playing_sound_threads.clear()

        if "NG" in stop_led_events:
            stop_led_events["NG"].set()
                
        LED_OK()

        for win in list(open_windows.values()):
            try:
                win.destroy()
            except Exception as e:
                logging(str(e))
                print(f"{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}: {e}")
        open_windows.clear()
        
        root.update_idletasks()
        root.update()

    elif flag == "NG":
        sound_path = os.path.join(os.getcwd(), "Sound", "Circulation_Error.wav")
        
        if flag in stop_sound_events:
            stop_sound_events[flag].set()
            
        stop_sound_events[flag] = threading.Event()
        
        t = threading.Thread(target=loop_sound, args=(flag, sound_path), daemon=True)
        playing_sound_threads[flag] = t
        t.start()

        if flag in stop_led_events:
            stop_led_events[flag].set()
        
        stop_led_events[flag] = threading.Event()
        
        t_led = threading.Thread(target=loop_led_NG, args=(flag,), daemon=True)
        led_threads[flag] = t_led
        t_led.start()
        
        if "UNKNOWN" in open_windows:
            try:
                open_windows["UNKNOWN"].destroy()
            except Exception as e:
                logging(str(e))
                pass
            del open_windows["UNKNOWN"]
            
        if "Machine_Missing" in open_windows:
            try:
                open_windows["Machine_Missing"].destroy()
            except Exception as e:
                logging(str(e))
                pass
            del open_windows["Machine_Missing"]

        root.update_idletasks()
        root.update()
        
        if flag in open_windows:
            return

        win = tk.Toplevel(root)
        win.title(flag)
        win.configure(bg="yellow")

        # 전체화면 설정
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()
        
        open_windows[flag] = win
        label = tk.Label(
            win, image=UI_Images[flag], borderwidth=0, highlightthickness=0
        )
        label.image = UI_Images[flag]
        label.pack(pady=10)

        def on_check():
            if flag in stop_sound_events:
                stop_sound_events[flag].set()
                
            if flag in stop_led_events:
                stop_led_events[flag].set()

            
            now_ts = time.time()
            for h in hwnd_list:
                NG_hwnd.append({
                    "hwnd": h,
                    "timestamp": now_ts
                })

            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)

    elif flag == "UNKNOWN":
        sound_path = os.path.join(os.getcwd(), "Sound", "Check_Remote_viewer_and_Scroll.wav")
        
        if flag in stop_sound_events:
            stop_sound_events[flag].set()
            
        stop_sound_events[flag] = threading.Event()
        
        t = threading.Thread(target=loop_sound, args=(flag, sound_path), daemon=True)
        playing_sound_threads[flag] = t
        t.start()
            
        if flag in open_windows or "NG" in open_windows:
            return
            
        if "Machine_Missing" in open_windows:
            try:
                open_windows["Machine_Missing"].destroy()
            except Exception as e:
                logging(str(e))
                pass
            del open_windows["Machine_Missing"]

        root.update_idletasks()
        root.update()
        
        win = tk.Toplevel(root)
        win.title(flag)
        win.configure(bg="yellow")

        # 전체화면 설정
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()

        open_windows[flag] = win
        label = tk.Label(
            win, image=UI_Images[flag], borderwidth=0, highlightthickness=0
        )
        label.image = UI_Images[flag]
        label.pack(pady=10)

        def on_check():
            if flag in stop_sound_events:
                stop_sound_events[flag].set()
                
            now_ts = time.time()
            for h in hwnd_list:
                UNKNOWN_hwnd.append({
                    "hwnd": h,
                    "timestamp": now_ts
                })
                
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)

    elif flag == "Machine_Missing":
        sound_path = os.path.join(os.getcwd(), "Sound", "Machine_Missing.wav")
        
        if flag in stop_sound_events:
            stop_sound_events[flag].set()
            
        stop_sound_events[flag] = threading.Event()
        
        t = threading.Thread(target=loop_sound, args=(flag, sound_path), daemon=True)
        playing_sound_threads[flag] = t
        t.start()
            
        if flag in open_windows or "NG" in open_windows or "UNKNOWN" in open_windows:
            return

        if "UNKNOWN" in open_windows:
            try:
                open_windows["UNKNOWN"].destroy()
            except Exception as e:
                logging(str(e))
                pass
            del open_windows["UNKNOWN"]

        root.update_idletasks()
        root.update()

        win = tk.Toplevel(root)
        win.title(flag)
        win.configure(bg="yellow")

        # 전체화면 설정
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()

        open_windows[flag] = win

        label = tk.Label(
            win, image=UI_Images[flag], borderwidth=0, highlightthickness=0
        )
        label.image = UI_Images[flag]
        label.pack(pady=10)

        def on_check():
            if flag in stop_sound_events:
                stop_sound_events[flag].set()
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)
    
def main():
    global NG_hwnd, UNKNOWN_hwnd
    UI_Images = {
        "NG": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Circulation_Error.png"))),
        "UNKNOWN": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Check_Remote_viewer_and_Scroll.png"))),
        "Machine_Missing": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Machine_Missing.png")))
    }
    while True:
        print("\n\n")
        now_ts = time.time()
        NG_hwnd = [item for item in NG_hwnd if now_ts - item["timestamp"] < 1800]
        UNKNOWN_hwnd = [item for item in UNKNOWN_hwnd if now_ts - item["timestamp"] < 1800]
        
        print(f"NG_hwnd: {NG_hwnd}")
        print(f"UNKNOWN_hwnd: {UNKNOWN_hwnd}")
        
        windows_images = []
        
        ignore_hwnds = [item["hwnd"] for item in NG_hwnd] + [item["hwnd"] for item in UNKNOWN_hwnd]
        
        windows = enum_windows()
        windows = [a for a in windows if "hmi_panel" in a[1]]
        # filtered_windows = [w for w in windows if w[0] not in ignore_hwnds]

        if len(windows) < 6:
            alarm_pop_up("Machine_Missing", UI_Images)
        elif len(windows) >= 6:
            windows.sort()
            for w in windows:
                # windows_images.append(capturing(w[0]))
                windows_images.append( (w[0], capturing(w[0])) )  # (hwnd, img)
            # flag = NG_Detecting(windows_images, target_img_list, ref_images)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(windows_images)) as executor:
                future_to_hwnd = {
                    executor.submit(send_http, img): hwnd
                    for (hwnd, img) in windows_images
                }
                results = []
                
                for future in concurrent.futures.as_completed(future_to_hwnd):
                    hwnd = future_to_hwnd[future]
                    try:
                        status = future.result()
                    except Exception as e:
                        logging(str(e))
                        status = "UNKNOWN"
                
                    results.append({
                        "hwnd": hwnd,
                        "status": status
                    })
                    
            print(f"Result: {results}")
            
            NG_list = [r["hwnd"] for r in results if r["status"] == "NG"]
            UNKNOWN_list = [r["hwnd"] for r in results if r["status"] == "UNKNOWN"]
            
            NG_list = [hwnd for hwnd in NG_list if hwnd not in ignore_hwnds]
            UNKNOWN_list = [hwnd for hwnd in UNKNOWN_list if hwnd not in ignore_hwnds]

            if len(NG_list) > 0:
                alarm_pop_up("NG", UI_Images, hwnd_list=NG_list)
            elif len(UNKNOWN_list) > 0:
                alarm_pop_up("UNKNOWN", UI_Images, hwnd_list=UNKNOWN_list)
            else:
                alarm_pop_up("OK", UI_Images)
            
        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()
    root.mainloop()