from ultralytics import YOLO

if __name__ == "__main__":
    model = YOLO("yolo26s.pt")

    model.train(
        data="data.yaml",
        imgsz=1280,
        batch=4,
        epochs=100,
        close_mosaic = 20
    )