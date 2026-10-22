#!/usr/bin/env python3
"""Emit the next WorkBuddy AskUserQuestion card from doctor JSON.

This helper does not render UI and does not read credentials. The WorkBuddy
agent is expected to pass the returned ``question`` object to its native
``AskUserQuestion`` tool. If that tool is unavailable, fall back to a plain-text
question and never ask for AK/SK in chat.
"""
import argparse
import json
from pathlib import Path
import sys

SCHEMA_VERSION = 1


def option(label, description):
    return {"label": label, "description": description}


def question(header, text, options, multi=False):
    return {
        "header": header[:12],
        "question": text,
        "multiSelect": bool(multi),
        "options": options[:4],
    }


def _next_card(status, account_confirmed=False, online_requested=False):
    credentials = status.get("credentials") or {}
    configuration = status.get("configuration") or {}
    online = status.get("online") or {}
    hpc = status.get("scnet_hpc") or {}

    if not account_confirmed:
        return {
            "next": "account",
            "question": question(
                "SCNet 账号",
                "你的 SCNet 账号是否已经开通目标区域的算力？",
                [
                    option("已开通", "继续检查凭证和区域"),
                    option("未开通", "先停止，按官方流程开通"),
                    option("不确定", "先查看开通说明"),
                ],
            ),
        }

    if not credentials.get("present"):
        options = [
            option("已配置，重新检查", "凭证已在共享库存或环境变量中"),
            option("去终端配置", "在用户自己的终端运行 scnet-hpc setup"),
            option("使用环境变量", "在用户终端导出三个 SCNET_OPENAPI_* 变量"),
            option("还没有凭证", "先查看获取 AK/SK 的官方路径"),
        ]
        card = {
            "next": "credentials",
            "question": question(
                "凭证",
                "SCNet OpenAPI 凭证准备怎么提供？",
                options,
            ),
        }
        if hpc.get("path"):
            card["terminal_command"] = (
                'python3 "{}" setup new --mode openapi'.format(hpc["path"])
            )
        return card

    if not configuration.get("ready"):
        region = configuration.get("region")
        cpu_queue = configuration.get("cpu_queue")
        hip_queue = configuration.get("hip_queue")
        if not region:
            return {
                "next": "region",
                "question": question(
                    "区域",
                    "这次使用哪个 SCNet region？",
                    [
                        option("使用当前默认 region", "沿用共享 scnet-hpc 配置"),
                        option("手动输入 region", "在对话中给出 region id"),
                        option("先发现可用区域", "运行只读 region 列表"),
                    ],
                ),
            }
        if not cpu_queue and not hip_queue:
            return {
                "next": "queue",
                "question": question(
                    "队列",
                    "CPU 和 DCU 使用哪些队列？",
                    [
                        option("使用 profile 中的队列", "沿用本地 profile"),
                        option("手动输入队列", "在对话中给出 queue 名称"),
                        option("稍后配置", "先停止，不提交作业"),
                    ],
                ),
            }
        return {
            "next": "configuration",
            "question": question(
                "配置",
                "本地配置还不完整，先补充 region 和队列。",
                [
                    option("使用 profile", "检查并修正 profile"),
                    option("手动输入", "在对话中给出 region/queue"),
                    option("稍后配置", "先停止"),
                ],
            ),
        }

    if online_requested:
        if online.get("ok"):
            return {"next": "ready", "question": None}
        return {
            "next": "blocked",
            "question": question(
                "在线验证",
                "在线只读检查失败，是否重试或查看下一步？",
                [
                    option("重试", "重新运行在线 doctor"),
                    option("查看下一步", "显示失败原因和命令"),
                    option("稍后", "先停止"),
                ],
            ),
            "error": online.get("error") or "online doctor failed",
        }

    return {
        "next": "online",
        "question": question(
            "在线验证",
            "本地前置条件已就绪，现在执行只读在线验证吗？",
            [
                option("现在验证", "检查账号、region 和队列"),
                option("稍后", "稍后自动或手动运行"),
            ],
        ),
    }


def next_card(status, account_confirmed=False, online_requested=False):
    card = _next_card(status, account_confirmed, online_requested)
    card.update(
        {
            "schema_version": SCHEMA_VERSION,
            "host": "workbuddy",
            "tool": "AskUserQuestion",
        }
    )
    return card


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, help="doctor JSON output file; stdin if omitted")
    parser.add_argument("--account-confirmed", action="store_true")
    parser.add_argument("--online", action="store_true", help="doctor was run with --online")
    args = parser.parse_args(argv)
    try:
        if args.status:
            status = json.loads(args.status.read_text(encoding="utf-8"))
        else:
            status = json.load(sys.stdin)
    except (OSError, ValueError) as exc:
        print("cannot read doctor JSON: {}".format(exc), file=sys.stderr)
        return 2
    if not isinstance(status, dict):
        print("doctor JSON must be an object", file=sys.stderr)
        return 2
    card = next_card(status, args.account_confirmed, args.online)
    card["doctor"] = {
        "openapi_ready": bool(status.get("openapi_ready")),
        "readiness": status.get("readiness") or {},
        "primary_blocker": status.get("primary_blocker"),
    }
    print(json.dumps(card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
