#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notify_wecom.py — 企业微信群机器人推送（纯 stdlib，零第三方依赖）。

设计（对齐 job_common 四件套契约的「enabled」语义）：
- webhook 为空 → 静默跳过（不报错、不抛），便于默认关闭。
- 网络/HTTP 错误 → 打印 warn 并返回 False，绝不中断主流程。
- 仅用 urllib，无外部库。

用法：
  python scripts/notify_wecom.py --webhook "<key>" --message "有新匹配"
  # 或在其它脚本里懒加载：from notify_wecom import notify
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="


def send_wecom(webhook: str | None, content: str, *, msgtype: str = "text",
               timeout: int = 10) -> bool:
    """向企业微信群机器人发送文本消息。

    webhook 仅传 key 部分（不含 URL 前缀）即可；若传完整 URL 也能用。
    返回 True 发送成功；webhook 空 / 出错返回 False（不抛）。
    """
    if not webhook:
        return False
    key = webhook.strip()
    if not key:
        return False
    url = key if "://" in key else WECOM_API + key
    payload = json.dumps(
        {"msgtype": msgtype, "text": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        data = json.loads(body)
        return bool(data.get("errcode", -1) == 0)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[warn] 企业微信推送失败（已忽略）: {exc}", file=sys.stderr)
        return False


def notify(title: str, message: str, webhook: str | None) -> bool:
    """带标题前缀的便捷推送。"""
    return send_wecom(webhook, f"【{title}】\n{message}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="企业微信群机器人推送")
    ap.add_argument("--webhook", help="群机器人 key（仅 key 部分；空则跳过）")
    ap.add_argument("--title", default="career-copilot")
    ap.add_argument("--message", required=True)
    args = ap.parse_args(argv)
    ok = notify(args.title, args.message, args.webhook)
    print("sent" if ok else "skipped")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
