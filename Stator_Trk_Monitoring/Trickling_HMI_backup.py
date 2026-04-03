import os, win32gui, win32ui, ctypes, cv2, time, datetime
import numpy as np

user32 = ctypes.windll.user32

def main():
    max_storage_for_logging_in_GB = 100
    max_images = max_storage_for_logging_in_GB*1024*1024/300
    save_path = r'C:\Users\uiv14138\Desktop\Trk_backup'
    hwnd = find_Trk_windows()
    os.makedirs(save_path, exist_ok=True)
    idx = 0
    while True:
        try:
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y-%m-%d_%H%M%S_") + f"{int(now.microsecond/1000):03d}.png"
            folder_name = now.strftime("%Y-%m-%d_%H")
            os.makedirs(os.path.join(save_path, folder_name), exist_ok=True)
            cv2.imwrite(os.path.join(save_path, folder_name, timestamp), capturing(hwnd))
            time.sleep(1.3)
            idx = idx + 1
            if idx > max_images:
                return None
        except Exception as e:
            print(e)
        

def find_Trk_windows():
    ref_img = cv2.imread(r"C:\Users\uiv14138\agent-alarm-service\Stator_Trk_Monitoring\Trk_ref_images\Trickling_ref.png")
    while True:
        try:
            windows = enum_windows()
            windows = [a for a in windows if "hmi_panel" in a[1]]
            for win in windows:
                result = find_matching_windows(capturing(win[0]), ref_img)
                if result:
                    cv2.imshow("Find matching windows", capturing(win[0]))
                    cv2.waitKey(1000*5)
                    cv2.destroyAllWindows()
                    return win[0]
            time.sleep(2)
        except Exception as e:
            print(e)

def find_matching_windows(win_img, ref_img):
    result = cv2.matchTemplate(win_img, ref_img, cv2.TM_CCOEFF_NORMED)
    max_val = result.max()
    
    if max_val > 0.9:
        print("Founded Matching Points :", max_val)
        return True
    else:
        print("일치 영역 없음", max_val)
        return False
    
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