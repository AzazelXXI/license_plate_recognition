import cv2
import torch
import time
import os
import argparse
import numpy as np
from ultralytics import YOLO


# Skeleton COCO 17 keypoints (if model trained on COCO pose)
COCO_SKELETON = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),  # Right arm
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),  # Left arm
    (0, 9),
    (9, 10),
    (10, 11),  # Right leg
    (0, 12),
    (12, 13),
    (13, 14),  # Left leg
    (0, 15),
    (15, 16),  # Head (optional; adjust as needed)
]


def order_points_four(pts: np.ndarray) -> np.ndarray:
    """Sắp xếp 4 điểm bất kỳ về thứ tự: top-left, top-right, bottom-right, bottom-left.

    pts: array shape (4,2)
    return: array shape (4,2) theo thứ tự chuẩn.
    """
    if isinstance(pts, list):
        pts = np.array(pts, dtype="float32")
    if pts.shape != (4, 2):
        raise ValueError("Cần đúng 4 điểm (shape (4,2))")

    # Tổng & hiệu để xác định góc
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)  # (y - x)

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")


def draw_rectangle_from_points(frame, pts, color=(0, 0, 255), thickness=2):
    """Vẽ hình chữ nhật (tứ giác đóng) nối 4 điểm (thứ tự bất kỳ)."""
    try:
        rect = order_points_four(pts)
    except Exception as e:
        # Nếu lỗi (không đủ 4 điểm) thì bỏ qua
        return frame
    poly = rect.reshape((-1, 1, 2)).astype(int)
    cv2.polylines(frame, [poly], isClosed=True, color=color, thickness=thickness)
    # Vẽ tâm & đánh dấu thứ tự
    for i, (x, y) in enumerate(rect):
        cv2.circle(frame, (int(x), int(y)), 4, (0, 255, 255), -1)
        cv2.putText(
            frame,
            str(i),
            (int(x) + 4, int(y) - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
        )
    return frame


def draw_pose(frame, results, kp_thresh=0.25):
    """Vẽ keypoints + skeleton nếu có."""
    if results.keypoints is None:
        return frame

    kpts_xy = results.keypoints.xy  # (num_instances, num_kpts, 2)
    kpts_conf = None
    if hasattr(results.keypoints, "conf") and results.keypoints.conf is not None:
        kpts_conf = results.keypoints.conf  # (num_instances, num_kpts)

    num_instances = kpts_xy.shape[0]
    num_kpts = kpts_xy.shape[1]

    for idx in range(num_instances):
        instance_pts = []
        # Thu thập và vẽ chấm
        for k in range(num_kpts):
            x, y = kpts_xy[idx, k]
            conf_k = kpts_conf[idx, k] if kpts_conf is not None else 1.0
            if conf_k < kp_thresh:
                continue
            cv2.circle(frame, (int(x), int(y)), 4, (0, 255, 255), -1)
            instance_pts.append([x, y])

        # Trường hợp model chỉ có 4 keypoints → nối thành tứ giác
        if num_kpts == 4 and len(instance_pts) == 4:
            ordered = order_points_four(np.array(instance_pts, dtype="float32"))
            poly = ordered.reshape((-1, 1, 2)).astype(int)
            cv2.polylines(frame, [poly], isClosed=True, color=(0, 0, 255), thickness=2)
            # Đánh số góc
            for i, (px, py) in enumerate(ordered):
                cv2.putText(
                    frame,
                    str(i),
                    (int(px) + 4, int(py) - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 255),
                    1,
                )

        # Skeleton mặc định cho 17 keypoints COCO
        elif num_kpts == 17:
            for a, b in COCO_SKELETON:
                if a < num_kpts and b < num_kpts:
                    xa, ya = kpts_xy[idx, a]
                    xb, yb = kpts_xy[idx, b]
                    if kpts_conf is not None:
                        if (
                            kpts_conf[idx, a] < kp_thresh
                            or kpts_conf[idx, b] < kp_thresh
                        ):
                            continue
                    cv2.line(
                        frame, (int(xa), int(ya)), (int(xb), int(yb)), (0, 200, 0), 2
                    )

    return frame


def draw_boxes(frame, results, conf_thresh=0.25):
    boxes = results.boxes
    if boxes is None or len(boxes) == 0:
        return frame
    for box in boxes:
        if box.conf is not None and float(box.conf[0]) < conf_thresh:
            continue
        (x1, y1, x2, y2) = box.xyxy[0].int().cpu().tolist()
        cls = int(box.cls[0]) if box.cls is not None else -1
        conf = float(box.conf[0]) if box.conf is not None else 0.0
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 160, 0), 2)
        cv2.putText(
            frame,
            f"{cls}:{conf:.2f}",
            (x1, max(y1 - 5, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 160, 0),
            2,
        )
    return frame


def parse_args():
    parser = argparse.ArgumentParser(description="YOLOv8 Pose Streaming")
    parser.add_argument(
        "--source", type=str, default="0", help="RTSP URL hoặc 0 cho webcam"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolov8n-pose.pt",
        help="Đường dẫn file pose model (.pt)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.25, help="Confidence threshold bbox"
    )
    parser.add_argument(
        "--kpconf", type=float, default=0.25, help="Confidence threshold keypoint"
    )
    parser.add_argument(
        "--noskel", action="store_true", help="Không vẽ skeleton, chỉ chấm keypoints"
    )
    parser.add_argument(
        "--resize",
        type=int,
        nargs=2,
        metavar=("W", "H"),
        help="Resize khung hình trước inference",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Source resolve
    source = 0 if args.source == "0" else args.source
    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG if isinstance(source, str) else 0)
    if not cap.isOpened():
        print("Không mở được nguồn video.")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚡ Device: {device}")

    if not os.path.exists(args.model):
        print(
            f"⚠️ Model '{args.model}' không tồn tại. Thử tải model mặc định 'yolov8n-pose.pt' (nếu có internet)."
        )
    model = YOLO(args.model).to(device)

    cv2.namedWindow("Pose", cv2.WINDOW_NORMAL)
    t_prev = time.time()
    frame_count = 0
    fps = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Mất tín hiệu hoặc kết thúc stream.")
            break

        if args.resize:
            frame = cv2.resize(frame, tuple(args.resize))

        # Inference
        results = model(frame, verbose=False)[0]

        # Vẽ bounding boxes
        frame = draw_boxes(frame, results, conf_thresh=args.conf)

        # Vẽ keypoints + skeleton
        if results.keypoints is not None:
            frame = draw_pose(frame, results, kp_thresh=args.kpconf)
            if args.noskel:
                pass  # (skeleton hiện vẽ chung, có thể tách nếu cần tuỳ biến)

        # FPS tính đơn giản
        frame_count += 1
        if frame_count >= 10:
            now = time.time()
            fps = frame_count / (now - t_prev)
            t_prev = now
            frame_count = 0
        cv2.putText(
            frame,
            f"FPS: {fps:.1f}",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )

        cv2.imshow("Pose", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
