import win32gui, win32ui, glob, cv2, os, ctypes, time, winsound, threading, datetime, random
import numpy as np
import tkinter as tk
import requests
import concurrent.futures

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


def alarm_pop_up(flag):
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

        # 라벨을 Bold 체로 변경
        label = tk.Label(
            win,
            text="Circulation",
            fg="red",
            bg="yellow",
            font=("Arial", 200, "bold")
        )
        label.pack(pady=20)

        label = tk.Label(
            win,
            text="Error",
            fg="red",
            bg="yellow",
            font=("Arial", 200, "bold")
        )
        label.pack(pady=20)

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

        win = tk.Toplevel(root)
        win.title(flag)
        win.configure(bg="yellow")

        # 전체화면 설정
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()

        open_windows[flag] = win

        # 라벨을 Bold 체로 변경
        label = tk.Label(
            win,
            text="Check",
            fg="red",
            bg="yellow",
            font=("Arial", 160, "bold")
        )
        label.pack(pady=10)
        
        
        label = tk.Label(
            win,
            text="Remote Viewer",
            fg="red",
            bg="yellow",
            font=("Arial", 160, "bold")
        )
        label.pack(pady=10)

        label = tk.Label(
            win,
            text="and Scroll",
            fg="red",
            bg="yellow",
            font=("Arial", 160, "bold")
        )
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

        win = tk.Toplevel(root)
        win.title(flag)
        win.configure(bg="yellow")

        # 전체화면 설정
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.lift()
        win.focus_force()

        open_windows[flag] = win

        # 라벨을 Bold 체로 변경
        label = tk.Label(
            win,
            text="Check",
            fg="red",
            bg="yellow",
            font=("Arial", 200, "bold")
        )
        label.pack(pady=10)

        label = tk.Label(
            win,
            text="Remote",
            fg="red",
            bg="yellow",
            font=("Arial", 200, "bold")
        )
        label.pack(pady=10)
        

        label = tk.Label(
            win,
            text="Viewer",
            fg="red",
            bg="yellow",
            font=("Arial", 200, "bold")
        )
        label.pack(pady=10)

        def on_check():
            if flag in open_windows:
                del open_windows[flag]
            win.destroy()

            pause_event.clear()
            threading.Thread(target=pause_timer, daemon=True).start()

        btn = tk.Button(win, text="Check", command=on_check, font=("Arial", 40))
        btn.pack(pady=30)
        
def NG_Detecting(images, target_img_list, ref_images):
    global Logging_path
    threshold = 0.8
    idx = 0
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[2:]
    master_flag = False
    for img in images:
        temp_flag = False
        is_Trk_Flag = False
        idx = idx + 1
        display_img = img.copy()
        NG_text = ''
        
        # Trk_ref_Check
        result = cv2.matchTemplate(img, ref_images['Trk'], cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val >= threshold:
            is_Trk_Flag = True
                
        for target_img in target_img_list:
            if not is_Trk_Flag and target_img[1] == "Trk_red_bar":
                continue
            
            result = cv2.matchTemplate(img, target_img[0], cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            if max_val >= threshold:
                master_flag = True
                temp_flag = True
                NG_text.append(target_img[1])
                h, w = target_img[0].shape[:2]
                top_left = max_loc
                bottom_right = (top_left[0] + w, top_left[1] + h)
                cv2.rectangle(display_img, top_left, bottom_right, (255, 0, 0), 2)
        if temp_flag:
            cv2.imwrite(os.path.join(Logging_path, f"{now_str}_{"_".join(NG_text)}_idx{idx}.png"), display_img)
    if master_flag:
        return "NG"
    else:
        return "OK"

def main():
    ref_images = loading_ref_images()
    target_img_list = loading_target_images()
    flag = "OK"
    flag = []
    while True:
        pause_event.wait()
        windows_images = []
        
        windows = enum_windows()
        windows = [a for a in windows if "hmi_panel" in a[1]]

        if len(windows) < 4:
            flag = "Machine_Missing"
            alarm_pop_up("Machine_Missing")
        elif len(windows) >= 4:
            windows.sort()
            for w in windows:
                windows_images.append(capturing(w[0]))
            # flag = NG_Detecting(windows_images, target_img_list, ref_images)
            for win_img in windows_images:
                flag.append(send_http(win_img))
            if "NG" in flag:
                alarm_pop_up("NG")
            elif "UNKNOWN" in flag:
                alarm_pop_up("UNKNOWN")
            else:
                alarm_pop_up("OK")
        time.sleep(60)
    
def main2():
    #ref_images = loading_ref_images()
    #target_img_list = loading_target_images()
    flag = "OK"
    flag = []
    while True:
        pause_event.wait()
        windows_images = []
        
        windows = enum_windows()
        windows = [a for a in windows if "hmi_panel" in a[1]]

        if len(windows) < 4:
            flag = "Machine_Missing"
            alarm_pop_up("Machine_Missing")
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
                alarm_pop_up("NG")
            elif "UNKNOWN" in flag:
                alarm_pop_up("UNKNOWN")
            else:
                alarm_pop_up("OK")
        time.sleep(60)

def test():
    print("test thread start")
    flag = ["OK", "NG", "UNKNOWN", "Machine_Missing"]
    while True:
        
        pause_event.wait()
        alarm_pop_up(flag[random.randint(0, 3)])
        time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=main2, daemon=True).start()
    #threading.Thread(target=test, daemon=True).start()
    root.mainloop()
