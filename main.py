import os, cv2, torch, argparse
from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser(description="License plate viewer (simple)")
    p.add_argument(
        "--source", type=str, default="0", help="Webcam index hoặc RTSP/file path"
    )
    p.add_argument(
        "--conf",
        type=float,
        default=0.05,
        help="Confidence threshold (lower default for more detections)",
    )
    p.add_argument("--imgsz", type=int, default=640, help="Image size")
    p.add_argument("--iou", type=float, default=0.6, help="IoU NMS")
    p.add_argument("--max-det", type=int, default=50, help="Max detections")
    p.add_argument("--device", type=str, default=None, help="cpu | cuda | cuda:0 ...")
    p.add_argument(
        "--resize", type=int, nargs=2, metavar=("W", "H"), help="Resize hiển thị"
    )
    p.add_argument(
        "--list-cams", action="store_true", help="Liệt kê webcam index rồi thoát"
    )
    p.add_argument(
        "--no-bbox", action="store_true", help="Ẩn khung bbox, chỉ hiển thị keypoints"
    )
    p.add_argument(
        "--ultra-style",
        action="store_true",
        help="Style giống Ultralytics (không đánh số thứ tự điểm)",
    )
    # Giảm nhấp nháy
    p.add_argument(
        "--smooth-alpha",
        type=float,
        default=0.4,
        help="Hệ số EMA (0-1) làm mượt bbox/kpts; 0=không cập nhật, 1=không làm mượt",
    )
    p.add_argument(
        "--persist",
        type=int,
        default=6,
        help="Số frame giữ lại đối tượng khi tạm mất (giảm nhấp nháy)",
    )
    p.add_argument(
        "--hyst-enter",
        type=float,
        default=0.06,
        help="Ngưỡng confidence để tạo/kích hoạt track (hysteresis). đặt hơi cao hơn --conf",
    )
    p.add_argument(
        "--hyst-exit",
        type=float,
        default=0.02,
        help="Ngưỡng duy trì track đang hoạt động (thấp hơn enter)",
    )
    p.add_argument(
        "--no-filter",
        action="store_true",
        help="Disable confidence gating: show/create tracks for all detections regardless of confidence",
    )
    p.add_argument(
        "--min-area",
        type=int,
        default=0,
        help="Minimum bounding box area in pixels to accept a detection (0 to disable)",
    )
    p.add_argument(
        "--min-aspect",
        type=float,
        default=2.0,
        help="Minimum width/height aspect ratio to accept a plate candidate (set 0 to disable)",
    )
    p.add_argument(
        "--max-aspect",
        type=float,
        default=6.0,
        help="Maximum width/height aspect ratio to accept a plate candidate (set 0 to disable)",
    )
    p.add_argument(
        "--min-width",
        type=int,
        default=0,
        help="Minimum bbox width in pixels to accept a detection (0 to disable)",
    )
    p.add_argument(
        "--min-height",
        type=int,
        default=0,
        help="Minimum bbox height in pixels to accept a detection (0 to disable)",
    )
    return p.parse_args()


def list_cams(n=10):
    found = []
    for i in range(n):
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            found.append(i)
            cap.release()
    return found


def open_stream(src: str):
    s = src.strip()
    if s.isdigit():
        cap = cv2.VideoCapture(int(s), cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(int(s))
        return cap
    return cv2.VideoCapture(s, cv2.CAP_FFMPEG)


def load_model(path: str, device: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy weights: {path}")
    m = YOLO(path).to(device)
    print(f"✅ Loaded model: {path} (task={getattr(m,'task','?')})")
    return m


def draw(frame, result, conf, no_bbox=False, ultra_style=False):
    boxes = result.boxes
    if boxes is None:
        return frame
    # Pose keypoints (expects 4 corners) if available
    has_kps = (
        hasattr(result, "keypoints")
        and result.keypoints is not None
        and getattr(result.keypoints, "xy", None) is not None
    )
    kps_xy = result.keypoints.xy if has_kps else None  # Tensor [N,K,2]
    # Simple skeleton for 4 điểm: 0-1-2-3-0 (nếu đủ 4 keypoints)
    for idx, b in enumerate(boxes):
        c = float(b.conf[0]) if b.conf is not None else 0.0
        if c < conf:
            continue
        cls = int(b.cls[0]) if b.cls is not None else 0
        if cls != 0:
            continue
        x1, y1, x2, y2 = b.xyxy[0].int().cpu().tolist()
        if not no_bbox:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"plate {c:.2f}"
        # Draw pose corners if present
        if has_kps and idx < len(kps_xy):
            pts = kps_xy[idx]
            if pts.shape[0] >= 4:
                # Take first 4 points
                pts4 = pts[:4].cpu().numpy().astype(int)
                if ultra_style:
                    # Ultralytics-like: uniform color circles + skeleton lines (cyan)
                    circle_color = (255, 255, 0)  # BGR cyan
                    for px, py in pts4:
                        cv2.circle(
                            frame, (int(px), int(py)), 4, circle_color, -1, cv2.LINE_AA
                        )
                    # skeleton edges
                    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
                    for a, bp in edges:
                        cv2.line(
                            frame,
                            tuple(pts4[a]),
                            tuple(pts4[bp]),
                            (0, 255, 255),
                            2,
                            cv2.LINE_AA,
                        )
                else:
                    # Custom: colored corners + polygon (no numbering if no_bbox & ultra_style false?)
                    colors = [
                        (255, 255, 0),
                        (255, 255, 0),
                        (255, 255, 0),
                        (255, 255, 0),
                    ]
                    for i, (px, py) in enumerate(pts4):
                        cv2.circle(
                            frame, (int(px), int(py)), 4, colors[i % 4], -1, cv2.LINE_AA
                        )
                        # bỏ số thứ tự nếu người dùng muốn giống pose => khi ultra_style True đã xử lý
                    # draw polygon in yellow for better visibility
                    cv2.polylines(
                        frame,
                        [pts4.reshape(-1, 1, 2)],
                        True,
                        (0, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
                label += " kp"
        if not no_bbox:
            cv2.putText(
                frame,
                label,
                (x1, max(0, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
    return frame


# ================== Tracking tối giản để giảm nhấp nháy ==================
class SimpleTrack:
    _next_id = 0

    def __init__(self, box, kps, conf, frame_idx):
        self.id = SimpleTrack._next_id
        SimpleTrack._next_id += 1
        self.box = box  # (x1,y1,x2,y2) float
        self.kps = kps  # ndarray (K,2) or None
        self.conf = conf
        self.last_frame = frame_idx
        self.active = True
        self.just_updated = True


def iou(b1, b2):
    # boxes tuple
    x1 = max(b1[0], b2[0])
    y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2])
    y2 = min(b1[3], b2[3])
    iw = max(0.0, x2 - x1)
    ih = max(0.0, y2 - y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    return inter / (a1 + a2 - inter + 1e-6)


def update_tracks(tracks, result, args, frame_idx):
    alpha = min(max(args.smooth_alpha, 0.0), 1.0)
    enter = args.hyst_enter
    exit_c = args.hyst_exit
    persist = max(args.persist, 0)
    # reset just_updated flags
    for t in tracks:
        t.just_updated = False
    new_boxes = []
    has_kps = (
        hasattr(result, "keypoints")
        and result.keypoints is not None
        and getattr(result.keypoints, "xy", None) is not None
    )
    kps_xy = result.keypoints.xy if has_kps else None
    boxes = result.boxes
    if boxes is not None:
        for idx, b in enumerate(boxes):
            c = float(b.conf[0]) if b.conf is not None else 0.0
            cls = int(b.cls[0]) if b.cls is not None else 0
            if cls != 0:
                continue
            # hysteresis filter (unless user disabled filtering)
            if c < enter and not getattr(args, "no_filter", False):
                # sẽ vẫn chấp nhận nếu khớp track cũ đang active và c >= exit
                pass
            x1, y1, x2, y2 = b.xyxy[0].cpu().tolist()
            kps = None
            if has_kps and idx < len(kps_xy) and kps_xy[idx].shape[0] >= 4:
                kps = kps_xy[idx][:4].cpu().numpy()
            # optional area filter
            area = (x2 - x1) * (y2 - y1)
            if args.min_area <= 0 or area >= args.min_area:
                new_boxes.append(((x1, y1, x2, y2), kps, c))

    # matching theo IoU
    for box, kps, c in new_boxes:
        best_iou = 0
        best_track = None
        for t in tracks:
            i = iou(box, t.box)
            if i > best_iou:
                best_iou = i
                best_track = t
        if best_track and best_iou >= 0.3:
            # hysteresis: nếu conf thấp hơn enter nhưng track đang active và conf >= exit thì giữ
            if c >= enter or (best_track.active and c >= exit_c):
                # EMA update
                if alpha < 1.0:
                    nb = [
                        alpha * box[i] + (1 - alpha) * best_track.box[i]
                        for i in range(4)
                    ]
                    best_track.box = tuple(nb)
                    if kps is not None and best_track.kps is not None and alpha < 1.0:
                        best_track.kps = alpha * kps + (1 - alpha) * best_track.kps
                    elif kps is not None:
                        best_track.kps = kps
                else:
                    best_track.box = box
                    if kps is not None:
                        best_track.kps = kps
                best_track.conf = c
                best_track.last_frame = frame_idx
                best_track.active = True
                best_track.just_updated = True
            else:
                # không đủ điều kiện giữ hoạt động
                best_track.active = False
        else:
            # tạo mới: nếu đủ ngưỡng enter hoặc user muốn no_filter thì tạo mọi detection
            if c >= enter or getattr(args, "no_filter", False):
                tracks.append(SimpleTrack(box, kps, c, frame_idx))

    # deactivate & prune
    alive = []
    for t in tracks:
        if frame_idx - t.last_frame <= persist:
            # nếu không cập nhật và quá hạn exit thì giảm active
            if not t.just_updated and t.conf < exit_c:
                t.active = False
            alive.append(t)
    return alive


def draw_tracks(frame, tracks, args):
    for t in tracks:
        if not t.active:
            continue
        x1, y1, x2, y2 = map(int, t.box)
        if not args.no_bbox:
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            cv2.putText(
                frame,
                f"plate {t.conf:.2f}",
                (x1, max(0, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 200, 0),
                2,
                cv2.LINE_AA,
            )
        if t.kps is not None and t.kps.shape[0] >= 4:
            pts4 = t.kps.astype(int)
            if args.ultra_style:
                for px, py in pts4:
                    cv2.circle(
                        frame, (int(px), int(py)), 4, (255, 255, 0), -1, cv2.LINE_AA
                    )
                edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
                for a, b in edges:
                    cv2.line(
                        frame,
                        tuple(pts4[a]),
                        tuple(pts4[b]),
                        (0, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
            else:
                colors = [(255, 255, 0), (255, 255, 0), (255, 255, 0), (255, 255, 0)]
                for i, (px, py) in enumerate(pts4):
                    cv2.circle(
                        frame, (int(px), int(py)), 4, colors[i % 4], -1, cv2.LINE_AA
                    )
                    # draw polygon in yellow
                    cv2.polylines(
                        frame, [pts4.reshape(-1, 1, 2)], True, (0, 255, 255), 2, cv2.LINE_AA
                    )
    return frame


def main():
    args = parse_args()
    if args.list_cams:
        print("Cameras:", list_cams())
        return
    if os.environ.get("QT_QPA_PLATFORM") is None:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    device = (
        args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu")
    )
    weight_path = "best.pt"  # cố định theo yêu cầu
    model = load_model(weight_path, device)
    cap = open_stream(args.source)
    if cap is None or not cap.isOpened():
        print("❌ Không mở được nguồn video")
        return
    cv2.namedWindow("Plate", cv2.WINDOW_NORMAL)
    tracks = []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        if args.resize:
            frame = cv2.resize(frame, tuple(args.resize))
        infer_conf = 0.0 if args.no_filter else args.conf
        res = model(
            frame,
            imgsz=args.imgsz,
            conf=infer_conf,
            iou=args.iou,
            classes=[0],
            verbose=False,
            max_det=args.max_det,
        )[0]
        # cập nhật track
        tracks = update_tracks(tracks, res, args, frame_idx)
        frame = draw_tracks(frame, tracks, args)
        frame_idx += 1
        cv2.imshow("Plate", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
