#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cache.py — LLM 响应语义缓存（T13）

设计：
  - 基于 SHA256(model + messages) 的键值文件缓存，按「相同输入 → 相同输出」语义去重。
  - 缓存目录：默认 .cache/llm/（可在构造时覆盖，便于测试）。
  - TTL：默认 7 天（8553600 秒），过期视为 miss。
  - 写入用临时文件 + os.replace 原子替换，避免并发半写。
  - 仅缓存 chat() 级别（字符串入 / 字符串出），符合 T13 验收（同 prompt 二次命中 < 10ms）。

线程/协程安全说明：
  - 单进程内多个协程并发写不同 key 是安全的（各自独立文件 + 原子 replace）。
  - 多进程共享同一目录理论上可能竞态，但本 skill 为单进程运行，不引入文件锁开销。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional, cast

DEFAULT_TTL_DAYS = 7
DEFAULT_CACHE_DIR = Path(".cache/llm")


def cache_key(model: str, messages: list[dict]) -> str:
    """对 (model, messages) 求稳定 SHA256 键；messages 序列化带 sort_keys 保证顺序无关。"""
    payload = json.dumps(
        {"model": model, "messages": messages},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SemanticCache:
    """按 model+messages 缓存 LLM 文本响应的文件缓存。"""

    def __init__(
        self,
        cache_dir: str | os.PathLike = DEFAULT_CACHE_DIR,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_days * 86400
        self.hits = 0
        self.misses = 0

    # ---- 内部 ----
    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    # ---- 公开 API ----
    def get(self, model: str, messages: list[dict]) -> Optional[str]:
        """命中且未过期返回缓存文本，否则 None（并计 miss）。"""
        key = cache_key(model, messages)
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.misses += 1
            return None
        if time.time() - float(rec.get("ts", 0)) > self.ttl_seconds:
            self.misses += 1
            return None
        self.hits += 1
        return cast("str | None", rec.get("value"))

    def put(self, model: str, messages: list[dict], value: str) -> None:
        """写入缓存（原子替换）。"""
        key = cache_key(model, messages)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "model": model, "value": value}
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path(key))

    def clear(self) -> int:
        """清空缓存目录，返回删除的文件数。"""
        if not self.cache_dir.exists():
            return 0
        n = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        return n

    def stats(self) -> dict:
        size = len(list(self.cache_dir.glob("*.json"))) if self.cache_dir.exists() else 0
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": (self.hits / total) if total else 0.0,
            "size": size,
        }


_default_cache: Optional["SemanticCache"] = None


def default_cache() -> "SemanticCache":
    """进程级单例缓存（默认 .cache/llm/）。"""
    global _default_cache
    if _default_cache is None:
        _default_cache = SemanticCache()
    return _default_cache
