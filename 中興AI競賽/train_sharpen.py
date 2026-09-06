from ultralytics import YOLO


def main():

    model = YOLO("yolo26m.pt")

    model.train(
        data=r"C:\Users\baifa\OneDrive\Desktop\中興AI競賽\dataset_sharpen\data_sharpen.yaml",

        imgsz=1024,

        batch=4,

        epochs=100,

        workers=8
    )


if __name__ == "__main__":
    main()