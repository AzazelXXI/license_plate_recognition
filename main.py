import os
import cv2
import torch
import argparse
import numpy as np
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Plate detection viewer")
    parser.add_argument(
        "--source",
        type=str,
        default="0",
        help="0/1... cho webcam hoặc đường dẫn file/RTSP",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="runs/pose_plate/weights/best.pt",
        help="Đường dẫn weights (.pt), mặc định dùng weights đã train",
    )
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument(
        "--resize",
        type=int,
        nargs=2,
        metavar=("W", "H"),
        help="Resize khung hình trước khi hiển thị",
    )
    parser.add_argument(
        "--list-cams",
        action="store_true",
        help="Liệt kê index camera khả dụng rồi thoát",
    )
    return parser.parse_args()


def open_capture(source_str: str):
    s = source_str.strip()
    if s.isdigit():  # webcam index
        idx = int(s)
        for backend in (cv2.CAP_V4L2, cv2.CAP_ANY):
            cap = cv2.VideoCapture(idx, backend)
            if cap.isOpened():
                return cap
        return None
    else:  # rtsp/http/file
        return cv2.VideoCapture(s, cv2.CAP_FFMPEG)


def _to_numpy(x):
    try:
        if isinstance(x, np.ndarray):
            return x
        if isinstance(x, torch.Tensor):
            return x.detach().cpu().numpy()
    except Exception:
        pass
    return np.asarray(x)


def _order_points_four(pts: np.ndarray) -> np.ndarray:
    """Sắp xếp 4 điểm theo thứ tự: top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, dtype="float32")
    if pts.shape[0] != 4:
        return pts
    s = pts.sum(axis=1)
    diff = pts[:, 1] - pts[:, 0]
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype="float32")


def draw_plates_and_pose(frame, results, conf_thresh=0.25, kp_thresh=0.10):
    boxes = results.boxes
    if boxes is None or len(boxes) == 0:
        return frame

    # Keypoints (n, K, 2) and optional confidence (n, K)
    kxy = None
    kcf = None
    if (
        getattr(results, "keypoints", None) is not None
        and results.keypoints.xy is not None
    ):
        kxy = _to_numpy(results.keypoints.xy)
        if getattr(results.keypoints, "conf", None) is not None:
            kcf = _to_numpy(results.keypoints.conf)

    for i in range(len(boxes)):
        box = boxes[i]
        conf = float(box.conf[0]) if box.conf is not None else 0.0
        if conf < conf_thresh:
            continue
        cls = int(box.cls[0]) if box.cls is not None else 0
        if cls != 0:  # Chỉ vẽ biển số (class 0)
            continue

        # Draw bbox
        x1, y1, x2, y2 = box.xyxy[0].int().cpu().tolist()
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # Draw 4 keypoints + polygon if available
        if kxy is not None and i < kxy.shape[0]:
            pts = kxy[i]
            if isinstance(pts, torch.Tensor):
                pts = _to_numpy(pts)
            if pts is None or pts.shape[0] < 4:
                continue

            # If have per-point confidence, filter very low-conf points
            mask = None
            if kcf is not None and i < kcf.shape[0]:
                confs = kcf[i]
                mask = confs >= kp_thresh
            else:
                mask = np.ones((pts.shape[0],), dtype=bool)

            pts_vis = pts[mask]
            if pts_vis.shape[0] >= 4:
                # Keep only first 4 visible; then order and draw
                pts4 = pts_vis[:4]
                ordered = _order_points_four(pts4)
                poly = ordered.reshape((-1, 1, 2)).astype(int)
                cv2.polylines(
                    frame, [poly], isClosed=True, color=(0, 0, 255), thickness=2
                )
                for px, py in ordered:
                    cv2.circle(frame, (int(px), int(py)), 4, (0, 255, 255), -1)
            else:
                # Fallback: draw whatever points are available
                for px, py in pts[:4]:
                    cv2.circle(frame, (int(px), int(py)), 4, (0, 255, 255), -1)

    return frame


def main():
    args = parse_args()

    if args.list_cams:
        available = []
        for i in range(10):
            cap_test = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if cap_test.isOpened():
                available.append(i)
                cap_test.release()
        print("Camera khả dụng:", available if available else "(không tìm thấy)")
        return

    # Đảm bảo hiển thị Qt trên X11 nếu Wayland thiếu plugin
    if os.environ.get("QT_QPA_PLATFORM") is None:
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    # Chọn weights: ưu tiên args.model -> runs/.../best.pt -> last.pt
    candidates = []
    if args.model:
        candidates.append(args.model)
    candidates += [
        "runs/pose_plate/weights/best.pt",
        "runs/pose_plate/weights/last.pt",
    ]
    seen = set()
    candidates = [m for m in candidates if not (m in seen or seen.add(m))]

    chosen = None
    for m in candidates:
        if os.path.exists(m):
            chosen = m
            break
    if not chosen:
        print(
            "❌ Không tìm thấy weights. Dùng --model để chỉ định hoặc đặt tại runs/pose_plate/weights/best.pt"
        )
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"⚡ Device: {device}")
    print(f"✅ Using model: {chosen}")
    model = YOLO(chosen).to(device)

    cap = open_capture(args.source)
    if cap is None or not cap.isOpened():
        print("❌ Không mở được nguồn video.")
        print("Gợi ý: --list-cams (webcam) hoặc dùng đường dẫn file/RTSP hợp lệ")
        return

    cv2.namedWindow("Plate", cv2.WINDOW_NORMAL)

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        if args.resize:
            frame = cv2.resize(frame, tuple(args.resize))

        res = model(frame, verbose=False)[0]
        frame = draw_plates_and_pose(frame, res, conf_thresh=args.conf)

        cv2.imshow("Plate", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
