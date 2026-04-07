import os, win32gui, win32ui, ctypes, cv2, time, datetime
import numpy as np

user32 = ctypes.windll.user32

def main():
    save_storage_in_GB = 100
    repeatation = int(save_storage_in_GB*1024*1024/300)
    interval_sec = 1.1
    save_path = r'C:\Users\uiv14138\Desktop\HMI_Backup'
    os.makedirs(save_path, exist_ok=True)
        
    for _ in range(repeatation):
        try:
            windows = enum_windows()
            windows = [a for a in windows if "hmi_panel" in a[1]]
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            folder_name = now.strftime("%Y-%m-%d_%H")
            os.makedirs(os.path.join(save_path, folder_name), exist_ok=True)
            for idx, win in enumerate(windows):
                cv2.imwrite(os.path.join(save_path, folder_name, timestamp+f"_{idx:02d}.png"), capturing(win[0]))
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
                win_list.append([hwnd, title])
    win32gui.EnumWindows(callback, None)
    return win_list

if __name__ =="__main__":
    main()