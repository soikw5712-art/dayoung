"""숏폼 영상 (1080×1920) 자동 생성.

구성: 장면별 자막 프레임(HTML→PNG) + 상품 이미지 → FFmpeg로 이어붙여 MP4.
장면 길이는 자막 글자 수로 계산한다. TTS 음성을 붙이면 음성 길이에 맞춰진다 (synthesize_speech 참고).
배경음악은 VIDEO_BGM_PATH에 저작권 무료 음원을 지정했을 때만 넣는다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html import escape
from pathlib import Path

from core.config import env
from generators.render import BRAND, image_src, render_pages

WIDTH, HEIGHT = 1080, 1920
MIN_SCENE_SEC, MAX_SCENE_SEC = 2.5, 6.0

CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: {WIDTH}px; height: {HEIGHT}px; background: {BRAND['bg']}; font-family: {BRAND['font']};
       color: {BRAND['ink']}; overflow: hidden; display: flex; flex-direction: column; }}
.photo {{ height: 1100px; margin: 160px 80px 0; border-radius: 40px; background: #fff center / contain no-repeat; }}
.caption {{ flex: 1; display: flex; align-items: center; justify-content: center; padding: 0 90px;
           font-size: 70px; font-weight: 800; line-height: 1.35; text-align: center; word-break: keep-all; }}
.hook {{ color: {BRAND['accent']}; }}
.note {{ position: absolute; bottom: 60px; width: 100%; text-align: center; font-size: 28px; color: {BRAND['muted']}; }}
"""


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg가 없습니다. pip install imageio-ffmpeg 를 실행하세요.")
        return exe


def scene_duration(text: str) -> float:
    # 한국어 자막 읽기 속도 ≈ 초당 7자
    return max(MIN_SCENE_SEC, min(MAX_SCENE_SEC, len(text) / 7 + 1.0))


def synthesize_speech(text: str, out_path: Path) -> Path | None:
    """TTS 연동 지점 (클로바 보이스, Typecast 등). 구현 전에는 None → 무음 영상."""
    return None


def build_frames(data: dict) -> list[str]:
    image = image_src(data["product"].get("image_url"))
    photo = f"<div class='photo' style=\"background-image:url('{escape(image)}')\"></div>" if image else ""
    frames = []
    for i, line in enumerate(data["video_script"]):
        cls = "caption hook" if i == 0 else "caption"
        frames.append(
            f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
            f"{photo}<div class='{cls}'>{escape(line)}</div>"
            "<div class='note'>쿠팡 파트너스 활동으로 수수료를 제공받을 수 있어요</div></body></html>"
        )
    return frames


def generate_video(content_path: Path) -> Path:
    data = json.loads(Path(content_path).read_text(encoding="utf-8"))
    folder = Path(content_path).parent / "video"
    frame_paths = [folder / f"scene_{i:02d}.png" for i in range(1, len(data["video_script"]) + 1)]
    render_pages(build_frames(data), frame_paths, WIDTH, HEIGHT)

    durations = [scene_duration(t) for t in data["video_script"]]
    concat = folder / "scenes.txt"
    lines = []
    for path, sec in zip(frame_paths, durations):
        lines += [f"file '{path.name}'", f"duration {sec:.2f}"]
    lines.append(f"file '{frame_paths[-1].name}'")  # concat demuxer는 마지막 파일을 한 번 더 적어야 길이가 반영됨
    concat.write_text("\n".join(lines), encoding="utf-8")

    out = folder / "short.mp4"
    cmd = [ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", concat.name]
    bgm = env("VIDEO_BGM_PATH")
    if bgm:
        cmd += ["-i", str(Path(bgm).resolve()), "-shortest", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", "-r", "30",
            "-c:v", "libx264", "-movflags", "+faststart", out.name]
    subprocess.run(cmd, cwd=folder, check=True, capture_output=True)
    return out
