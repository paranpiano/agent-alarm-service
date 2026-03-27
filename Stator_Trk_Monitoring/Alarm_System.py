import win32gui, win32ui, glob, cv2, os, ctypes, time, winsound, threading, datetime, random
import numpy as np
import tkinter as tk
import requests
import concurrent.futures
from PIL import Image, ImageTk

global open_windows, pause_event
global Logging_path, target_path, Trk_ref_image_path

Logging_path = r'AAAAAAAAAAAAAAAAAAA'
target_path = r'C:\Users\uiv14247\OneDrive - Vitesco Technologies\Desktop\Stator_Trk_Monitoring'
Trk_ref_image_path = r'AAAAAAAAAAAAAAAAAAAAAAAAAAAAA'

user32 = ctypes.windll.user32
open_windows = {}

pause_event = threading.Event()
pause_event.set()

root = tk.Tk()
root.withdraw()

def loading_ref_images():
    global Trk_ref_image_path
    ref_images = {
        "Trk": cv2.imread(Trk_ref_image_path)
    }
    return ref_images

def loading_target_images():
    global target_path
    target_list = glob.glob(os.path.join(target_path, "*.png"))
    target_img_list = [[cv2.imread(a), os.path.basename(a).replace(".png","")] for a in target_list]
    return target_img_list

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
        print("Capture error:", e)
        return None

def send_http(img):
    url = "http://127.0.0.1:8000/api/v1/analyze"
    results = []
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
    except:
        return "UNKNOWN"

def pause_timer():
    print("waiting for 60 sec")
    time.sleep(60)
    pause_event.set()


def alarm_pop_up(flag, UI_Images):
    global open_windows
    print(flag)

    if flag == "OK":
        for win in list(open_windows.values()):
            try:
                win.destroy()
            except:
                pass
        open_windows.clear()
        return

    elif flag == "NG":
        sound_path = os.path.join(os.getcwd(), "Sound", "Circulation_Error.wav")
        try:
            play_sound(sound_path)
        except Exception as e:
            print("Sound play error:", e)

        if "UNKNOWN" in open_windows:
            try:
                open_windows["UNKNOWN"].destroy()
            except:
                pass
            del open_windows["UNKNOWN"]
            
        if "Machine_Missing" in open_windows:
            try:
                open_windows["Machine_Missing"].destroy()
            except:
                pass
            del open_windows["Machine_Missing"]

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

        label = tk.Label(
            win, image=UI_Images[flag], borderwidth=0, highlightthickness=0
        )
        label.image = UI_Images[flag]
        label.pack(pady=10)

        def on_check():
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

            pause_event.clear()
            threading.Thread(target=pause_timer, daemon=True).start()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)

    elif flag == "UNKNOWN":
        sound_path = os.path.join(os.getcwd(), "Sound", "Check_Remote_viewer_and_Scroll.wav")
        try:
            play_sound(sound_path)
        except Exception as e:
            print("Sound play error:", e)
            
        if flag in open_windows or "NG" in open_windows:
            return
            
        if "Machine_Missing" in open_windows:
            try:
                open_windows["Machine_Missing"].destroy()
            except:
                pass
            del open_windows["Machine_Missing"]
            
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
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

            pause_event.clear()
            threading.Thread(target=pause_timer, daemon=True).start()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)

    elif flag == "Machine_Missing":
        sound_path = os.path.join(os.getcwd(), "Sound", "Machine_Missing.wav")
        try:
            play_sound(sound_path)
        except Exception as e:
            print("Sound play error:", e)
            
        if flag in open_windows or "NG" in open_windows or "UNKNOWN" in open_windows:
            return

        if "UNKNOWN" in open_windows:
            try:
                open_windows["UNKNOWN"].destroy()
            except:
                pass
            del open_windows["UNKNOWN"]
            
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
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

            pause_event.clear()
            threading.Thread(target=pause_timer, daemon=True).start()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)
    
def main():
    UI_Images = {
        "NG": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Circulation_Error.png"))),
        "UNKNOWN": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Check_Remote_viewer_and_Scroll.png"))),
        "Machine_Missing": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Machine_Missing.png")))
    }
    flag = "OK"
    while True:
        pause_event.wait()
        windows_images = []
        
        windows = enum_windows()
        windows = [a for a in windows if "hmi_panel" in a[1]]

        if len(windows) < 4:
            flag = "Machine_Missing"
            alarm_pop_up("Machine_Missing", UI_Images)
        elif len(windows) >= 4:
            windows.sort()
            for w in windows:
                windows_images.append(capturing(w[0]))
            # flag = NG_Detecting(windows_images, target_img_list, ref_images)
            flag = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(windows_images)) as executor:
                future_to_idx = {
                    executor.submit(send_http, img): idx
                    for idx, img in enumerate(windows_images)
                }
            
                for future in concurrent.futures.as_completed(future_to_idx):
                    try:
                        result = future.result()
                    except Exception:
                        result = "UNKNOWN"
                    flag.append(result)
            if "NG" in flag:
                alarm_pop_up("NG", UI_Images)
            elif "UNKNOWN" in flag:
                alarm_pop_up("UNKNOWN", UI_Images)
            else:
                alarm_pop_up("OK", UI_Images)
        time.sleep(60)

def test():
    print("test thread start")
    flag = ["OK", "NG", "UNKNOWN", "Machine_Missing"]
    UI_Images = {
        "NG": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Circulation_Error.png"))),
        "UNKNOWN": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Check_Remote_viewer_and_Scroll.png"))),
        "Machine_Missing": ImageTk.PhotoImage(Image.open(os.path.join(os.getcwd(), "UI_Images", "Machine_Missing.png")))
    }
    while True:
        pause_event.wait()
        alarm_pop_up(flag[random.randint(0, 3)], UI_Images)
        time.sleep(5)

if __name__ == "__main__":
    # threading.Thread(target=main, daemon=True).start()
    threading.Thread(target=test, daemon=True).start()
    root.mainloop()