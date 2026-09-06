import cv2
import numpy as np
from pathlib import Path


ROOT = Path(
    r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\dataset_sharpen"
)


kernel = np.array([
    [0, -1, 0],
    [-1, 5, -1],
    [0, -1, 0]
], dtype=np.float32)


# =========================================================
# 支援中文路徑的圖片讀取
# =========================================================

def imread_unicode(path):

    try:
        data = np.fromfile(
            str(path),
            dtype=np.uint8
        )

        image = cv2.imdecode(
            data,
            cv2.IMREAD_COLOR
        )

        return image

    except Exception as e:
        print(f"讀取錯誤：{path}")
        print(e)
        return None


# =========================================================
# 支援中文路徑的圖片儲存
# =========================================================

def imwrite_unicode(path, image):

    suffix = Path(path).suffix.lower()

    if suffix in [".jpg", ".jpeg"]:
        ext = ".jpg"

    elif suffix == ".png":
        ext = ".png"

    elif suffix == ".bmp":
        ext = ".bmp"

    else:
        ext = ".jpg"

    try:
        success, encoded = cv2.imencode(
            ext,
            image
        )

        if not success:
            return False

        encoded.tofile(
            str(path)
        )

        return True

    except Exception as e:
        print(f"儲存錯誤：{path}")
        print(e)
        return False


# =========================================================
# 處理 train / val / test
# =========================================================

splits = [
    "train",
    "val",
    "test"
]


for split in splits:

    image_dir = (
        ROOT
        / "images"
        / split
    )

    if not image_dir.exists():

        print(
            f"找不到：{image_dir}"
        )

        continue


    print(
        f"\n正在處理 {split}..."
    )


    image_paths = [
        p
        for p in image_dir.iterdir()
        if p.suffix.lower()
        in [".jpg", ".jpeg", ".png", ".bmp"]
    ]


    success_count = 0
    failed_count = 0


    for i, img_path in enumerate(
        image_paths,
        start=1
    ):

        # 中文路徑讀取
        image = imread_unicode(
            img_path
        )


        if image is None:

            print(
                f"讀取失敗：{img_path}"
            )

            failed_count += 1

            continue


        # 輕微銳化
        sharpened = cv2.filter2D(
            image,
            -1,
            kernel
        )


        # 中文路徑儲存
        success = imwrite_unicode(
            img_path,
            sharpened
        )


        if success:
            success_count += 1

        else:
            print(
                f"寫入失敗：{img_path}"
            )

            failed_count += 1


        if i % 100 == 0:

            print(
                f"{split} 已處理 "
                f"{i}/{len(image_paths)}"
            )


    print(
        f"{split} 完成："
        f"成功 {success_count} 張，"
        f"失敗 {failed_count} 張"
    )


print(
    "\n全部完成！"
)