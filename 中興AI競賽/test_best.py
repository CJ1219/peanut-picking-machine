from ultralytics import YOLO


def main():

    model = YOLO(
        r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\runs\detect\train-13\weights\best.pt"
    )

    results = model.val(
        data=r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\dataset_sharpen\data_sharpen.yaml",

        split="test",

        imgsz=1024,

        batch=4,

        workers=8,

        plots=True
    )

    print(results)


if __name__ == "__main__":
    main()