import os, glob, tqdm, random, shutil
import cv2
import numpy as np
import matplotlib.pyplot as plt
from multiprocessing import Pool, cpu_count

def main():
    path = r'C:\Users\uiv14247\Downloads\sample_img_backup'
    save_path = r'C:\Users\uiv14247\Downloads\img_diff_test'
    thr = 0.6
    backup_folder = r'C:\Users\uiv14247\Downloads\Stator Monitoring System duplicated drop'
    # remove_duplicate_images(path)
    # analyze_folder_image_differences(path, sample_size=3000, bin_width=0.05, xlim=(0,10), use_log_scale=False)
    # visualize_threshold_matches(path, save_path, threshold=thr, sample_size=2500)
    for _ in range(1000000):
        remove_near_duplicate_images_mp(path, backup_folder, threshold=thr)

def remove_near_duplicate_images_mp(folder, backup_folder, threshold=0.1, workers=None):
    os.makedirs(backup_folder, exist_ok=True)

    img_paths = glob.glob(os.path.join(folder, "*.png"))
    random.shuffle(img_paths)

    tasks = []
    for i in range(len(img_paths) - 1):
        tasks.append((img_paths[i], img_paths[i+1], threshold, backup_folder))

    if workers is None:
        workers = max(1, cpu_count() - 1)

    with Pool(workers) as pool:
        list(tqdm.tqdm(
            pool.imap_unordered(process_pair, tasks),
            total=len(tasks),
            desc="Parallel duplicate removal"
        ))

def process_pair(args):
    img_a, img_b, threshold, backup_folder = args

    if not os.path.exists(img_b):
        return

    img1 = cv2.imread(img_a)
    img2 = cv2.imread(img_b)

    if img1 is None or img2 is None:
        return

    if img1.shape != img2.shape:
        return

    diff = cv2.absdiff(img1, img2)
    diff_val = diff.max(axis=2)

    nonzero = diff_val > 0
    if not np.any(nonzero):
        score = 0.0
    else:
        mean_nonzero = diff_val[nonzero].mean()
        ratio = np.count_nonzero(nonzero) / diff_val.size
        score = mean_nonzero * ratio

    if score <= threshold:
        dst = os.path.join(backup_folder, os.path.basename(img_b))
        if os.path.exists(img_b):
            shutil.move(img_b, dst)


def remove_near_duplicate_images(folder, backup_folder, threshold=0.1):
    os.makedirs(backup_folder, exist_ok=True)
    backup_folder = os.path.join(backup_folder, str(threshold))
    os.makedirs(backup_folder, exist_ok=True)

    img_paths = sorted(glob.glob(os.path.join(folder, "*.png")))
    random.shuffle(img_paths)
    if len(img_paths) < 2:
        return

    prev_path = img_paths[0]
    prev_img = cv2.imread(prev_path)

    for curr_path in tqdm.tqdm(img_paths[1:], desc="Removing duplicates"):
        curr_img = cv2.imread(curr_path)

        if prev_img is None or curr_img is None:
            prev_img = curr_img
            prev_path = curr_path
            continue

        if prev_img.shape != curr_img.shape:
            prev_img = curr_img
            prev_path = curr_path
            continue

        diff = cv2.absdiff(prev_img, curr_img)
        diff_val = diff.max(axis=2)

        nonzero = diff_val > 0
        if not np.any(nonzero):
            score = 0.0
        else:
            mean_nonzero = diff_val[nonzero].mean()
            ratio = np.count_nonzero(nonzero) / diff_val.size
            score = mean_nonzero * ratio

        if score <= threshold:
            dst = os.path.join(backup_folder, os.path.basename(curr_path))
            shutil.move(curr_path, dst)
        else:
            prev_img = curr_img
            prev_path = curr_path

def visualize_threshold_matches(folder, output_dir, threshold=1, sample_size=1000):
    os.makedirs(output_dir, exist_ok=True)

    img_paths = glob.glob(os.path.join(folder, "*.png"))
    if len(img_paths) < 2:
        return

    if len(img_paths) > sample_size:
        img_paths = random.sample(img_paths, sample_size)

    img_paths.sort()

    pair_idx = 0
    prev_img = cv2.imread(img_paths[0])

    for idx, img_path in enumerate(tqdm.tqdm(img_paths[1:], desc="Processing pairs"), start=1):
        curr_img = cv2.imread(img_path)

        if prev_img is None or curr_img is None:
            prev_img = curr_img
            continue

        if prev_img.shape != curr_img.shape:
            prev_img = curr_img
            continue

        diff = cv2.absdiff(prev_img, curr_img)
        diff_val = diff.max(axis=2)

        nonzero = diff_val > 0
        if not np.any(nonzero):
            score = 0.0
        else:
            mean_nonzero = diff_val[nonzero].mean()
            ratio = np.count_nonzero(nonzero) / diff_val.size
            score = mean_nonzero * ratio

        if score <= threshold and np.any(nonzero):
            mask = (diff_val > 0).astype(np.uint8) * 255
            num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

            h, w = prev_img.shape[:2]
            canvas = np.zeros((h, w * 2, 3), dtype=np.uint8)
            canvas[:, :w] = prev_img
            canvas[:, w:] = curr_img

            for label in range(1, num_labels):
                x, y, bw, bh, area = stats[label]
                if area == 0:
                    continue

                cv2.rectangle(
                    canvas,
                    (x, y),
                    (x + bw, y + bh),
                    (255, 0, 0),
                    2
                )
                cv2.rectangle(
                    canvas,
                    (x + w, y),
                    (x + w + bw, y + bh),
                    (255, 0, 0),
                    2
                )

            int_part = int(score)
            frac_part = score - int_part
            score_str = f"{int_part:03d}{frac_part:.9f}"  # 정수 3자리 + 소수 9자리
            score_str = score_str.replace("0.", ".", 1)

            fname = f"Score_{score_str}_pair_{pair_idx:04d}.png"
            out_path = os.path.join(output_dir, fname)
            cv2.imwrite(out_path, canvas)

            pair_idx += 1

        prev_img = curr_img


def remove_duplicate_images(folder):
    img_list = glob.glob(os.path.join(folder, "*.png"))
    seen = []
    removed = 0
    for img_path in tqdm.tqdm(img_list[-900:]):
        img = cv2.imread(img_path)
        if img is None:
            continue

        is_duplicate = False

        for s in seen:
            if img.shape == s.shape and np.array_equal(img, s):
                is_duplicate = True
                break

        if is_duplicate:
            os.remove(img_path)
            print("Delete:", os.path.basename(img_path))
            removed += 1
        else:
            seen.append(img)

def analyze_folder_image_differences(folder, sample_size=2000, bin_width=1, xlim=(0, 255), use_log_scale=False):
    img_paths = glob.glob(os.path.join(folder, "*.png"))
    if len(img_paths) < 2:
        return

    if len(img_paths) > sample_size:
        img_paths = random.sample(img_paths, sample_size)

    random.shuffle(img_paths)

    diff_scores = []

    prev_img = cv2.imread(img_paths[0])

    for img_path in tqdm.tqdm(img_paths[1:]):
        curr_img = cv2.imread(img_path)

        if prev_img is None or curr_img is None:
            prev_img = curr_img
            continue

        if prev_img.shape != curr_img.shape:
            prev_img = curr_img
            continue

        diff = cv2.absdiff(prev_img, curr_img)
        diff_val = diff.max(axis=2)

        nonzero = diff_val > 0
        if np.any(nonzero):
            mean_nonzero = diff_val[nonzero].mean()
            ratio = np.count_nonzero(nonzero) / diff_val.size
            score = mean_nonzero * ratio
            diff_scores.append(score)
        else:
            diff_scores.append(0)

        prev_img = curr_img

    bins = np.arange(0, 256 + bin_width, bin_width)

    plt.figure(figsize=(10, 4))
    plt.hist(diff_scores, bins=bins)

    plt.xlim(xlim)
    plt.xlabel("Weighted Mean Difference")
    plt.ylabel("Frequency (shape only)")
    plt.title("Distribution of Image-to-Image Differences")

    if use_log_scale:
        plt.yscale("log")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()