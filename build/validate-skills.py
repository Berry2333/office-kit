#!/usr/bin/env python3
"""校验 skills/*/SKILL.md 的 frontmatter 与基本结构（对应 DSH skill-filesystem 规则）。

用法: python3 build/validate-skills.py [skills_dir]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REQUIRED = ("name", "description")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("文件不以 YAML frontmatter 开头")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("frontmatter 未闭合")
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError("frontmatter 不是映射")
    return meta, parts[2]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "skills")
    if not root.is_dir():
        print(f"找不到技能目录: {root}", file=sys.stderr)
        return 2
    failures = 0
    seen: set[str] = set()
    for skill_md in sorted(root.glob("*/SKILL.md")):
        skill_dir = skill_md.parent.name
        try:
            meta, body = split_frontmatter(skill_md.read_text(encoding="utf-8"))
            for key in REQUIRED:
                if not meta.get(key):
                    raise ValueError(f"缺少 frontmatter 字段 {key}")
            name = str(meta["name"])
            desc = str(meta["description"])
            if name != skill_dir:
                raise ValueError(f"name '{name}' 与目录名 '{skill_dir}' 不一致")
            if not NAME_RE.match(name):
                raise ValueError(f"name '{name}' 不是 kebab-case")
            if name in seen:
                raise ValueError(f"技能名重复: {name}")
            if len(desc) < 20:
                raise ValueError("description 过短（<20 字符）")
            if len(desc) > 1200:
                raise ValueError("description 过长（>1200 字符）")
            if "office-kit" not in body:
                raise ValueError("正文未提及 office-kit 调用方式")
            seen.add(name)
            print(f"OK   {name:14s} desc={len(desc):4d}字 body={len(body):5d}字")
        except Exception as exc:  # noqa: BLE001 - 校验脚本要汇总所有错误
            failures += 1
            print(f"FAIL {skill_dir}: {exc}", file=sys.stderr)
    if failures:
        print(f"\n{failures} 个技能未通过", file=sys.stderr)
        return 1
    print(f"\n全部通过：{len(seen)} 个技能")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
