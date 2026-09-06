from pathlib import Path
from collections import Counter

ROOT = Path(
    r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\dataset_sharpen"
)

CLASS_NAMES = {
    0: "normal",
    1: "mold",
    2: "small"
}

NAME_TO_ID = {
    "normal": 0,
    "mold": 1,
    "small": 2
}

splits = ["train", "val", "test"]

total_counter = Counter()

for split in splits:

    label_dir = ROOT / "labels" / split

    counter = Counter()
    label_count = 0

    print(f"\n正在統計 {split}...")

    for label_file in label_dir.glob("*.txt"):

        label_count += 1

        with open(
            label_file,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                first_value = line.split()[0]

                # -----------------------------
                # YOLO 數字格式
                # 0 / 1 / 2
                # -----------------------------
                if first_value.isdigit():

                    class_id = int(first_value)

                # -----------------------------
                # 類別名稱格式
                # normal / mold / small
                # -----------------------------
                else:

                    class_name = first_value.lower()

                    if class_name not in NAME_TO_ID:

                        print(
                            f"未知類別：{class_name} "
                            f"({label_file.name})"
                        )

                        continue

                    class_id = NAME_TO_ID[class_name]

                counter[class_id] += 1
                total_counter[class_id] += 1


    print(f"\n===== {split} =====")

    print(
        f"標註檔數量：{label_count}"
    )

    for class_id, name in CLASS_NAMES.items():

        print(
            f"{name}: "
            f"{counter[class_id]} instances"
        )

    print(
        f"總 instances: "
        f"{sum(counter.values())}"
    )


print("\n============================")
print("===== 整個 Dataset =====")
print("============================")

for class_id, name in CLASS_NAMES.items():

    print(
        f"{name}: "
        f"{total_counter[class_id]} instances"
    )

print(
    f"\n全部 instances: "
    f"{sum(total_counter.values())}"
)