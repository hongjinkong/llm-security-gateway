#!/usr/bin/env python3
"""D-090 S2 — DanInTheWild 표집 오프라인 재현. garak 이미지 안에서 `--network none`으로만 돌린다.

실제 실행(garak 0.15.1 cli → probewise 하네스)에서 전역 `random`이 DanInTheWild 표집 전까지 쓰이는
지점을 같은 순서로 따라 한다. generator·detector는 만들지 않고 target에 요청하지 않는다.

  1. random.seed(seed)                       cli.py 458~463 — 시작 때 한 번
  2. command.hint(...)                        cli.py 688 "This run can be sped up" — random.random() 한 번
  3. 앞 8개 프로브 적재(_plugins.load_plugin) probewise 하네스 순서(garak.log `probe init`)
     변형 B만: RANTI 적재 직후 backoff 재시도 한 번(rest.py `_call_model`과 같은 fibo·max_value=70, 기본 jitter)
  4. DanInTheWild 적재 → __init__에서 _prune_data(soft_probe_prompt_cap)
  5. prompts를 실행 때처럼 `{generator.name}` 치환(DANProbeMeta.probe) → 텍스트 sha256

  docker run --rm --network none --entrypoint python \
    -v "$PWD/scripts:/scripts:ro" -v "$PWD/garak:/work:ro" garak-runner \
    /scripts/d090_replay_dan_sampling.py --variant A > results/d090_replay_A_1.json

결과 JSON만 stdout에 쓴다. garak이 찍는 문구는 stderr로 돌린다. garak/logs는 마운트하지 않는다
(공유 garak.log에 쓰지 않는다). 새 채점 규칙은 없다.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

SEED = 20260819
DAN_ITW = "probes.dan.DanInTheWild"
RANTI = "probes.dan.ChatGPT_Developer_Mode_RANTI"
# probewise 하네스는 프로브 이름을 정렬해 하나씩 적재한다. DanInTheWild 앞은 이 8개다(garak.log `probe init`).
PRE_PROBES = (
    "probes.dan.Ablation_Dan_11_0",
    "probes.dan.AntiDAN",
    "probes.dan.AutoDANCached",
    RANTI,
    "probes.dan.ChatGPT_Developer_Mode_v2",
    "probes.dan.ChatGPT_Image_Markdown",
    "probes.dan.DAN_Jailbreak",
    "probes.dan.DUDE",
)
GENERATOR_NAME_PATTERN = "{generator.name}"


def text_sha256(text: str) -> str:
    """d090_compare.py도 이 함수로 리포트 쪽 텍스트를 해시한다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_like_probe(prompts: list[str], generator_name: str) -> list[str]:
    """DANProbeMeta.probe와 같은 규칙 — `{generator.name}`이 있을 때만 format한다."""
    generator = SimpleNamespace(name=generator_name)
    return [p.format(generator=generator) if GENERATOR_NAME_PATTERN in p else p for p in prompts]


def run_replay(*, variant: str, seed: int, load_probe: Callable[[str], Any], hint: Callable[[], None],
               backoff_retry_once: Callable[[], float],
               pre_probes: tuple[str, ...] = PRE_PROBES, target: str = DAN_ITW) -> tuple[Any, float | None, list[str]]:
    """전역 random을 쓰는 순서만 맡는다. 반환: (target 프로브, 변형 B의 jitter 대기값, 호출 순서)."""
    if variant not in ("A", "B"):
        raise ValueError(f"변형은 A 또는 B: {variant!r}")
    if variant == "B" and RANTI not in pre_probes:
        raise ValueError(f"변형 B는 {RANTI} 적재 직후에 재시도를 넣는다 — 목록에 없다")
    trace: list[str] = []
    random.seed(seed)
    trace.append("seed")
    hint()
    trace.append("hint")
    wait = None
    for name in pre_probes:
        load_probe(name)
        trace.append(name)
        if variant == "B" and name == RANTI:
            wait = backoff_retry_once()
            trace.append("backoff")
    probe = load_probe(target)
    trace.append(target)
    return probe, wait, trace


def garak_backoff_retry_once() -> float:
    """rest.py `_call_model`의 데코레이터와 같은 인자로 재시도를 한 번 일으키고 실제 대기값을 돌려준다.

    jitter는 지정하지 않는다(garak도 지정하지 않는다) — 설치된 backoff의 기본 jitter가 쓰인다.
    on_backoff 처리기는 대기값을 받아 적기만 하고 random을 쓰지 않는다.
    """
    import backoff

    waits: list[float] = []
    calls = {"n": 0}

    @backoff.on_exception(backoff.fibo, RuntimeError, max_value=70,
                          on_backoff=lambda details: waits.append(details["wait"]))
    def flaky() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("D-090 재현: 서버 오류 500 자리")
        return True

    flaky()
    if len(waits) != 1 or calls["n"] != 2:
        raise RuntimeError(f"재시도가 정확히 한 번이 아니다: waits={waits}, calls={calls['n']}")
    return float(waits[0])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", choices=("A", "B"), required=True)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--generator-config", type=Path, default=Path("/work/anythingllm_rest.json"),
                    help="실행 때 -G로 넘긴 설정. `{generator.name}` 치환에 쓸 이름만 읽는다")
    a = ap.parse_args(argv)

    generator_name = json.loads(a.generator_config.read_text(encoding="utf-8"))["rest"]["RestGenerator"]["name"]

    with contextlib.redirect_stdout(sys.stderr):
        from importlib.metadata import version
        import platform

        import garak
        from garak import _config, _plugins, command
        from garak.data import path as data_path

        _config.load_base_config()
        _config.run.seed = a.seed
        _config.run.generations = 10
        probe, wait, trace = run_replay(
            variant=a.variant, seed=a.seed,
            load_probe=_plugins.load_plugin,
            hint=lambda: command.hint("D-090 재현: cli.py 688 안내 자리", logging=None),
            backoff_retry_once=garak_backoff_retry_once,
        )
        data_file = data_path / probe.prompt_file
        raw = data_file.read_bytes()
        items = json.loads(raw)
        texts = format_like_probe(list(probe.prompts), generator_name)
        out = {
            "variant": a.variant,
            "seed": a.seed,
            "garak_version": garak.__version__,
            "backoff_version": version("backoff"),
            "python": platform.python_version(),
            "soft_probe_prompt_cap": probe.soft_probe_prompt_cap,
            "data_file": str(data_file),
            "data_sha256": hashlib.sha256(raw).hexdigest(),
            "data_items": len(items),
            "data_items_nonempty": sum(1 for p in items if p),
            "generator_name": generator_name,
            "formatted_count": sum(1 for p in probe.prompts if GENERATOR_NAME_PATTERN in p),
            "jitter_wait": wait,
            "trace": trace,
            "prompt_count": len(texts),
            "prompt_sha256": [text_sha256(t) for t in texts],
        }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
