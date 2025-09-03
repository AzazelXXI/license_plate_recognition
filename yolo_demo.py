"""
YOLO License Plate Recognition Demo

Hướng dẫn từng bước để hiểu và sử dụng YOLO cho nhận diện biển số xe.
"""

import cv2
import numpy as np
from pathlib import Path


def setup_yolo():
    """
    Khởi tạo YOLO model
    """
    try:
        from ultralytics import YOLO

        print("✅ Đang tải YOLO model...")
        model = YOLO("yolov8n.pt")
        print("✅ Model đã sẵn sàng!")
        return model
    except ImportError:
        print("❌ Vui lòng cài đặt: pip install ultralytics")
        return None


def detect_objects(model, image_path):
    """
    Detect các đối tượng trong ảnh

    Args:
        model: YOLO model
        image_path: Đường dẫn đến ảnh

    Returns:
        results: Kết quả detection
    """
    if model is None:
        return None

    # Chạy detection
    results = model(image_path)

    # In kết quả
    for r in results:
        print(f"📸 Detected {len(r.boxes)} objects:")
        if len(r.boxes) > 0:
            for box in r.boxes:
                class_id = int(box.cls)
                confidence = float(box.conf)
                class_name = model.names[class_id]
                print(f"  - {class_name}: {confidence:.2f}")

    return results


def visualize_results(results, save_path="detection_result.jpg"):
    """
    Hiển thị và lưu kết quả detection
    """
    if results is None:
        return

    for r in results:
        # Vẽ bounding boxes lên ảnh
        im_array = r.plot()

        # Chuyển từ RGB sang BGR để lưu với OpenCV
        im_bgr = cv2.cvtColor(im_array, cv2.COLOR_RGB2BGR)

        # Lưu ảnh
        cv2.imwrite(save_path, im_bgr)
        print(f"✅ Đã lưu kết quả tại: {save_path}")

        return im_array


if __name__ == "__main__":
    print("🚀 YOLO License Plate Recognition Demo")
    print("=" * 50)

    # Khởi tạo model
    model = setup_yolo()

    if model:
        # Test với ảnh mẫu (nếu có)
        image_path = "images/sample_plate.png"
        if Path(image_path).exists():
            print(f"📷 Analyzing image: {image_path}")
            results = detect_objects(model, image_path)
            visualize_results(results)
        else:
            print(f"⚠️  Không tìm thấy ảnh tại: {image_path}")
            print("💡 Hãy đặt ảnh biển số vào thư mục images/")
