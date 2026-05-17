#!/usr/bin/env python3
"""九萬畝 自動挖地腳本 (PC + Android 模擬器 / ADB + OpenCV 影像辨識)

運作方式:
  截圖(ADB) -> 影像辨識找按鈕(OpenCV 模板比對) -> 模擬點擊(ADB) -> 等待 -> 重複

因為遊戲是像素風原生 App,畫面是單一 canvas,抓不到 UI 元素,
所以用「截圖 + 模板圖片比對 + 座標點擊」是唯一可靠的自動化方式。

使用前請先閱讀 auto_mining_guide.md。
"""

import argparse
import logging
import os
import random
import signal
import subprocess
import sys
import time

import cv2
import numpy as np
import yaml

LOG = logging.getLogger("auto_mining")
_STOP = False


def _handle_sigint(signum, frame):
    global _STOP
    _STOP = True
    LOG.warning("收到中斷訊號,將在目前步驟結束後安全停止...")


signal.signal(signal.SIGINT, _handle_sigint)


def setup_logging(log_file: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def rand_in(value, default=0.0):
    """value 可以是數字,或 [min, max] 取隨機;方便做擬人化延遲。"""
    if value is None:
        return float(default)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return random.uniform(float(value[0]), float(value[1]))
    return float(value)


class Adb:
    """封裝模擬器的 ADB 連線:連線、截圖、點擊、滑動、返回鍵。"""

    def __init__(self, adb_path: str, serial: str | None):
        self.adb_path = adb_path or "adb"
        self.serial = serial

    def _base_cmd(self) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def connect(self) -> None:
        if self.serial and ":" in self.serial:
            LOG.info("連線模擬器 ADB: %s", self.serial)
            subprocess.run(
                [self.adb_path, "connect", self.serial],
                capture_output=True, text=True, timeout=15,
            )
        result = subprocess.run(
            self._base_cmd() + ["get-state"],
            capture_output=True, text=True, timeout=15,
        )
        state = result.stdout.strip()
        if state != "device":
            raise RuntimeError(
                f"ADB 裝置未就緒 (state={state!r} stderr={result.stderr.strip()!r})。"
                "請確認模擬器已開、ADB 埠正確,參考 auto_mining_guide.md。"
            )
        LOG.info("ADB 裝置就緒。")

    def screencap(self):
        """回傳 BGR numpy 影像 (OpenCV 格式)。"""
        result = subprocess.run(
            self._base_cmd() + ["exec-out", "screencap", "-p"],
            capture_output=True, timeout=20,
        )
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(
                f"截圖失敗: {result.stderr.decode(errors='ignore').strip()}"
            )
        img = cv2.imdecode(
            np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if img is None:
            raise RuntimeError("截圖解碼失敗 (畫面資料無效)。")
        return img

    def tap(self, x: int, y: int) -> None:
        subprocess.run(
            self._base_cmd() + ["shell", "input", "tap", str(int(x)), str(int(y))],
            capture_output=True, timeout=15,
        )

    def swipe(self, x1, y1, x2, y2, dur_ms=300) -> None:
        subprocess.run(
            self._base_cmd() + ["shell", "input", "swipe",
                                 str(int(x1)), str(int(y1)),
                                 str(int(x2)), str(int(y2)), str(int(dur_ms))],
            capture_output=True, timeout=15,
        )

    def back(self) -> None:
        subprocess.run(
            self._base_cmd() + ["shell", "input", "keyevent", "4"],
            capture_output=True, timeout=15,
        )


def find_template(screen, template_path: str, threshold: float):
    """在 screen 中找 template,回傳 (中心x, 中心y, 信心值) 或 None。"""
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f"找不到模板圖片: {template_path}")
    th, tw = template.shape[:2]
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    cx = max_loc[0] + tw // 2
    cy = max_loc[1] + th // 2
    return cx, cy, float(max_val)


class MiningBot:
    def __init__(self, config: dict, dry_run: bool = False):
        self.cfg = config
        self.dry_run = dry_run
        adb_cfg = config.get("adb", {})
        self.adb = Adb(adb_cfg.get("adb_path", "adb"), adb_cfg.get("serial"))
        s = config.get("settings", {})
        self.template_dir = s.get("template_dir", "templates")
        self.default_threshold = float(s.get("default_threshold", 0.85))
        self.loop_count = int(s.get("loop_count", 50))
        self.loop_delay = s.get("loop_delay", [2, 5])
        self.tap_jitter = int(s.get("tap_jitter_px", 4))
        self.debug_dir = s.get("debug_dir")
        self.sequence = config.get("sequence", [])
        if not self.sequence:
            raise ValueError("config 的 sequence 是空的,沒有任何步驟可執行。")

    def _tpath(self, name: str) -> str:
        return os.path.join(self.template_dir, name)

    def _save_debug(self, screen, tag: str) -> None:
        if not self.debug_dir:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        path = os.path.join(self.debug_dir, f"{int(time.time())}_{tag}.png")
        cv2.imwrite(path, screen)

    def _jittered_tap(self, x: int, y: int) -> None:
        jx = x + random.randint(-self.tap_jitter, self.tap_jitter)
        jy = y + random.randint(-self.tap_jitter, self.tap_jitter)
        if self.dry_run:
            LOG.info("[DRY-RUN] 應點擊 (%d, %d)", jx, jy)
            return
        self.adb.tap(jx, jy)

    def run_step(self, step: dict) -> bool:
        """執行單一步驟。回傳 True 表示成功/可繼續,False 表示此 cycle 失敗。"""
        name = step.get("name", step.get("action", "?"))
        action = step.get("action")
        threshold = float(step.get("threshold", self.default_threshold))
        timeout = float(step.get("timeout", 10))
        optional = bool(step.get("optional", False))

        LOG.info("步驟: %s (%s)", name, action)

        if action == "wait":
            time.sleep(rand_in(step.get("seconds"), 1.0))
            return True

        if action == "back":
            if not self.dry_run:
                self.adb.back()
            time.sleep(rand_in(step.get("after_delay"), 1.0))
            return True

        if action == "tap":
            self._jittered_tap(int(step["x"]), int(step["y"]))
            time.sleep(rand_in(step.get("after_delay"), 1.0))
            return True

        if action == "swipe":
            if not self.dry_run:
                self.adb.swipe(step["x1"], step["y1"], step["x2"], step["y2"],
                               step.get("duration_ms", 300))
            time.sleep(rand_in(step.get("after_delay"), 1.0))
            return True

        if action in ("tap_template", "wait_template"):
            tpl = step["template"]
            deadline = time.time() + timeout
            hit = None
            while time.time() < deadline and not _STOP:
                screen = self.adb.screencap()
                hit = find_template(screen, self._tpath(tpl), threshold)
                if hit:
                    break
                time.sleep(0.8)

            if not hit:
                self._save_debug(self.adb.screencap(), f"miss_{tpl}")
                if optional:
                    LOG.info("  找不到 %s,但為選用步驟,跳過。", tpl)
                    return True
                LOG.warning("  逾時找不到模板 %s,此 cycle 中止。", tpl)
                return False

            cx, cy, conf = hit
            LOG.info("  找到 %s 信心=%.3f 位置=(%d,%d)", tpl, conf, cx, cy)
            if action == "tap_template":
                ox = int(step.get("offset_x", 0))
                oy = int(step.get("offset_y", 0))
                self._jittered_tap(cx + ox, cy + oy)
            time.sleep(rand_in(step.get("after_delay"), 1.0))
            return True

        LOG.error("未知的 action: %s,此 cycle 中止。", action)
        return False

    def run_cycle(self, idx: int) -> bool:
        LOG.info("===== 第 %d 塊地 開始 =====", idx)
        for step in self.sequence:
            if _STOP:
                return False
            ok = self.run_step(step)
            if not ok:
                LOG.warning("第 %d 塊地 流程中斷,進入下一輪。", idx)
                # 嘗試按返回鍵回到已知畫面,避免卡死
                if not self.dry_run:
                    for _ in range(3):
                        self.adb.back()
                        time.sleep(1)
                return False
        LOG.info("===== 第 %d 塊地 完成 =====", idx)
        return True

    def run(self) -> None:
        self.adb.connect()
        if self.dry_run:
            LOG.info("DRY-RUN 模式:只辨識不點擊。")
        done = 0
        i = 0
        while not _STOP:
            i += 1
            if self.loop_count > 0 and i > self.loop_count:
                LOG.info("已達設定的 loop_count=%d,停止。", self.loop_count)
                break
            success = self.run_cycle(i)
            if success:
                done += 1
            delay = rand_in(self.loop_delay, 3.0)
            LOG.info("本輪結束 (累計成功 %d 塊)。休息 %.1f 秒...", done, delay)
            slept = 0.0
            while slept < delay and not _STOP:
                time.sleep(min(0.5, delay - slept))
                slept += 0.5
        LOG.info("腳本結束。總共成功挖地 %d 塊。", done)


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        LOG.error("找不到設定檔: %s", path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_check(args) -> None:
    """測試 ADB 連線 + 截圖,把截圖存成檔案方便你裁切模板。"""
    cfg = load_config(args.config)
    adb_cfg = cfg.get("adb", {})
    adb = Adb(adb_cfg.get("adb_path", "adb"), adb_cfg.get("serial"))
    adb.connect()
    screen = adb.screencap()
    out = args.out or "screen_check.png"
    cv2.imwrite(out, screen)
    h, w = screen.shape[:2]
    LOG.info("截圖成功,解析度 %dx%d,已存成 %s", w, h, out)
    LOG.info("用看圖軟體打開它,裁切出各按鈕當作 templates/ 內的模板圖片。")


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    if args.max_cycles is not None:
        cfg.setdefault("settings", {})["loop_count"] = args.max_cycles
    bot = MiningBot(cfg, dry_run=args.dry_run)
    bot.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="九萬畝 自動挖地腳本")
    parser.add_argument("-c", "--config", default="mining_config.yaml",
                        help="設定檔路徑 (預設 mining_config.yaml)")
    parser.add_argument("--log-file", default="auto_mining.log")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="測試 ADB 連線並存一張截圖")
    p_check.add_argument("-o", "--out", help="截圖輸出檔名")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="開始自動挖地")
    p_run.add_argument("--dry-run", action="store_true",
                       help="只辨識不點擊,用來驗證模板比對")
    p_run.add_argument("--max-cycles", type=int,
                       help="覆寫設定檔的 loop_count")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    setup_logging(args.log_file)
    try:
        args.func(args)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        LOG.error("執行失敗: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
