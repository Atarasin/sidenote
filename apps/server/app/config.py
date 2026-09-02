"""配置加载：config.yaml（默认，入库）+ config.local.yaml（本地覆盖，不入库）。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

SERVER_DIR = Path(__file__).resolve().parent.parent  # apps/server
REPO_ROOT = SERVER_DIR.parent.parent

MAX_UPLOAD_BYTES_FALLBACK = 300 * 1024 * 1024


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@lru_cache(maxsize=1)
def load_config() -> dict:
    """读取 config.yaml 并用 config.local.yaml 深度覆盖。"""
    cfg: dict = yaml.safe_load((SERVER_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
    local_path = SERVER_DIR / "config.local.yaml"
    if local_path.exists():
        local: dict = yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        cfg = deep_merge(cfg, local)
    return cfg


def reset_config_cache() -> None:
    load_config.cache_clear()


def data_root() -> Path:
    """本地运行时数据根目录（书籍、缓存、费用记录；gitignore 的 data/）。"""
    env = os.environ.get("SIDENOTE_DATA")
    if env:
        return Path(env)
    return REPO_ROOT / "data"


def max_upload_bytes() -> int:
    return int(load_config().get("upload", {}).get("max_bytes", MAX_UPLOAD_BYTES_FALLBACK))
