import os, win32gui, win32ui, ctypes, cv2, time, datetime
import numpy as np

user32 = ctypes.windll.user32

def main():
    logging_time_in_minute = 5
    interval_sec = 5
    save_path = r''
    os.makedirs(save_path, exist_ok=True)
    
    windows = enum_windows()
    windows = [a for a in windows if "hmi_panel" in a[1]]
        
    for _ in range(int(logging_time_in_minute*60/interval_sec)):
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        for idx, win in enumerate(windows):
            try:
                cv2.imwrite(os.path.join(save_path, timestamp+f"_{idx:3d}.png"), capturing(win[0]))
            except Exception as e:
                print(e)
        time.sleep(interval_sec)
    
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

def enum_windows():
    win_list = []
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.strip():
                win_list.append([hwnd, title, win32gui.GetWindowRect(hwnd)])
    win32gui.EnumWindows(callback, None)
    return win_list

if __name__ =="__main__":
    main()