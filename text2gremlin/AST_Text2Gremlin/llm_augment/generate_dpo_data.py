# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
DPO 偏好数据生成脚本

基于已有的 text2gremlin 数据，生成 Groovy vs Gremlin 的偏好对齐训练数据。
三类任务：
  A 类：多任务组合 — 选 2~5 条简单 gremlin 合成 groovy（chosen）和纯 gremlin（rejected）
  B 类：单任务 — 纯 gremlin（chosen）vs 包一层 groovy（rejected），数量为 A/C 的 1/3
  C 类：复杂长链拆解 — groovy 拆步骤（chosen）vs 原始长链（rejected）

用法:
    python -m llm_augment.generate_dpo_data
    python -m llm_augment.generate_dpo_data --input output/text2gremlin_pairs_xxx.json
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from glob import glob
from typing import List, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from llm_augment.generalize_llm import get_llm_config, load_config


# ---- Pydantic 模型 ----


class DPOCandidate(BaseModel):
    """DPO 候选（chosen 或 rejected）"""

    style: str = Field(description="groovy 或 gremlin")
    code: str = Field(description="代码内容")


class DPOSampleA(BaseModel):
    """A 类：多任务组合的 LLM 输出"""

    instruction: str = Field(description="合成的自然语言任务描述")
    chosen: DPOCandidate
    rejected: DPOCandidate
    preference_reason: List[str] = Field(description="偏好原因")


class DPOSampleB(BaseModel):
    """B 类：单任务的 LLM 输出"""

    chosen: DPOCandidate
    rejected: DPOCandidate
    preference_reason: List[str] = Field(description="偏好原因")


class DPOSampleC(BaseModel):
    """C 类：复杂长链拆解的 LLM 输出"""

    chosen: DPOCandidate
    preference_reason: List[str] = Field(description="偏好原因")


class DPOSampleCWithSkip(BaseModel):
    """C 类带跳过标识"""

    skip: bool = Field(description="是否跳过（该语句不适合改写为 groovy）")
    chosen: Optional[DPOCandidate] = None
    preference_reason: Optional[List[str]] = None


# ---- 数据加载与预处理 ----


def load_pairs(input_path: str) -> List[dict]:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pairs", [])


def find_latest_pairs(output_dir: str = "output") -> Optional[str]:
    pattern = os.path.join(output_dir, "text2gremlin_pairs_*.json")
    files = sorted(glob(pattern))
    return files[-1] if files else None


def count_gremlin_steps(gremlin: str) -> int:
    """粗略统计 gremlin 语句的步数（以 '.' 分隔的方法调用数）"""
    in_str = False
    dots = 0
    for i, ch in enumerate(gremlin):
        if ch in ("'", '"'):
            in_str = not in_str
        elif ch == "." and not in_str:
            dots += 1
    return dots


def classify_pairs(pairs: List[dict]) -> dict:
    """将数据按步数分类。"""
    short, medium, long_ = [], [], []
    for p in pairs:
        steps = count_gremlin_steps(p["gremlin"])
        p["_steps"] = steps
        if steps <= 5:
            short.append(p)
        elif steps > 8:
            long_.append(p)
        else:
            medium.append(p)
    return {"short": short, "medium": medium, "long": long_}


def select_related_group(short_pairs: List[dict], n: int) -> List[dict]:
    """从短查询中选取 n 条相关的查询（同 label 或同操作类型优先）。"""
    label_groups = {}
    for p in short_pairs:
        g = p["gremlin"]
        labels = []
        idx = 0
        while True:
            pos = g.find("hasLabel('", idx)
            if pos == -1:
                break
            start = pos + len("hasLabel('")
            end = g.find("'", start)
            if end != -1:
                labels.append(g[start:end])
            idx = end + 1 if end != -1 else len(g)

        key = tuple(sorted(set(labels))) if labels else ("_no_label",)
        label_groups.setdefault(key, []).append(p)

    candidates = sorted(label_groups.values(), key=len, reverse=True)
    for group in candidates:
        if len(group) >= n:
            return random.sample(group, n)

    return random.sample(short_pairs, min(n, len(short_pairs)))


# ---- Prompt 构建 ----


def build_prompt_type_a(selected_pairs: List[dict]) -> str:
    """A 类 prompt：多任务组合，合成 groovy 和纯 gremlin"""
    queries_text = ""
    for i, p in enumerate(selected_pairs, 1):
        queries_text += f"  {i}. 自然语言: {p['text']}\n     Gremlin: {p['gremlin']}\n"

    styles = [p.get("style", "") for p in selected_pairs]
    style_hint = ""
    if any("zh" in s for s in styles):
        style_hint = "中文"
    elif any("en" in s for s in styles):
        style_hint = "英文"
    else:
        style_hint = "与原始输入语句的语言风格保持一致"

    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你 {len(selected_pairs)} 条来自同一场景的简单 Gremlin 查询及其自然语言描述。
请你：
1. 将这些查询组合成一个复合任务，生成一段自然语言描述（instruction）
2. 用 Groovy 命令式写法实现这个复合任务（chosen，style=groovy）
3. 用纯 Gremlin 函数式写法实现同样的任务（rejected，style=gremlin）
4. 说明为什么 Groovy 写法更优

## 原始子查询
{queries_text}

## 要求
1. instruction 必须是一个自然的复合任务描述，语言风格为{style_hint}，像真实用户会说的话
2. Groovy 写法：用 def 定义中间变量，每条 traversal 调用 .next() 或 .toList()，最后返回一个 map
3. 纯 Gremlin 写法：用 project/union/inject 等方式强行写成一条语句，要体现出复杂和难读
4. 两种写法的语义必须等价
5. Groovy 中的变量命名要统一、清晰
6. preference_reason 说明 Groovy 更优的具体原因

## 输出格式（严格 JSON）
```json
{{
  "instruction": "...",
  "chosen": {{
    "style": "groovy",
    "code": "..."
  }},
  "rejected": {{
    "style": "gremlin",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```"""
    return prompt


def build_prompt_type_b(pair: dict) -> str:
    """B 类 prompt：单任务，纯 gremlin 更好，生成包一层 groovy 的负样本"""
    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你一条简单的 Gremlin 查询，这条查询用单条 Gremlin 就能很好地完成。
请你生成一个"过度工程化"的 Groovy 写法作为负样本。

## 原始查询
自然语言: {pair["text"]}
Gremlin: {pair["gremlin"]}

## 要求
1. rejected 的 Groovy 写法要体现"过度包装"：用 def 变量、.next()、返回 map 等，但实际上完全没必要
2. chosen 就是原始的 Gremlin 语句
3. preference_reason 说明为什么单条 Gremlin 更好

## 输出格式（严格 JSON）
```json
{{
  "chosen": {{
    "style": "gremlin",
    "code": "..."
  }},
  "rejected": {{
    "style": "groovy",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```"""
    return prompt


def build_prompt_type_c(pair: dict) -> str:
    """C 类 prompt：复杂长链拆解为 groovy"""
    prompt = f"""你是一个图数据库专家，擅长 Gremlin 和 Groovy 编程。

## 任务
给你一条复杂的长链 Gremlin 查询。请判断：
- 如果这条查询适合拆解为多步 Groovy 写法（更清晰、更易读），请生成 Groovy 版本
- 如果这条查询用 Gremlin 写已经是最优的（无法有意义地拆分），请标记 skip=true

## 原始查询
自然语言: {pair["text"]}
Gremlin: {pair["gremlin"]}

## 要求
1. 如果适合改写：
   - chosen 的 Groovy 写法要把长链拆成多个有意义的中间步骤
   - 用 def 定义中间变量，变量命名清晰
   - 最后返回结果
   - preference_reason 说明为什么拆解后更好
2. 如果不适合改写（skip=true）：
   - chosen 和 preference_reason 可以不填
   - 不要强行包一层 Groovy

## 输出格式（严格 JSON）

适合改写时：
```json
{{
  "skip": false,
  "chosen": {{
    "style": "groovy",
    "code": "..."
  }},
  "preference_reason": ["...", "..."]
}}
```

不适合改写时：
```json
{{
  "skip": true
}}
```"""
    return prompt


# ---- LLM 调用 ----


async def call_llm(
    client: AsyncOpenAI,
    prompt: str,
    llm_config: dict,
) -> str:
    """统一的 LLM 调用，返回原始文本内容"""
    response = await client.chat.completions.create(
        model=llm_config["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=llm_config["temperature"],
    )
    content = response.choices[0].message.content

    if not content or not content.strip():
        raise ValueError("LLM 返回内容为空")
    return content


def extract_json(content: str) -> dict:
    """从 LLM 返回内容中提取 JSON"""
    json_str = content
    if "```json" in json_str:
        json_str = json_str.split("```json")[1].split("```")[0]
    elif "```" in json_str:
        json_str = json_str.split("```")[1].split("```")[0]
    return json.loads(json_str.strip())


# ---- 单条任务处理 ----


async def process_type_a(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> Optional[dict]:
    """处理 A 类任务：多任务组合"""
    max_retries = llm_config["max_retries"]

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_a(task["pairs"])
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)
                validated = DPOSampleA(**data)

                return {
                    "task_id": task["task_id"],
                    "task_type": "A",
                    "domain": "movie",
                    "source_queries": [{"text": p["text"], "gremlin": p["gremlin"]} for p in task["pairs"]],
                    "input": {"instruction": validated.instruction},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": validated.rejected.model_dump(),
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError):
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "A", f"A 类失败(重试{max_retries}次)")
            except Exception as e:
                return _error_result(task["task_id"], "A", f"A 类异常: {e}")


async def process_type_b(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> Optional[dict]:
    """处理 B 类任务：单任务，纯 gremlin 更好"""
    max_retries = llm_config["max_retries"]
    pair = task["pair"]

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_b(pair)
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)
                validated = DPOSampleB(**data)

                return {
                    "task_id": task["task_id"],
                    "task_type": "B",
                    "domain": "movie",
                    "input": {"instruction": pair["text"]},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": validated.rejected.model_dump(),
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError):
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "B", f"B 类失败(重试{max_retries}次)")
            except Exception as e:
                return _error_result(task["task_id"], "B", f"B 类异常: {e}")


async def process_type_c(
    client: AsyncOpenAI,
    task: dict,
    semaphore: asyncio.Semaphore,
    llm_config: dict,
) -> Optional[dict]:
    """处理 C 类任务：复杂长链拆解"""
    max_retries = llm_config["max_retries"]
    pair = task["pair"]

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_prompt_type_c(pair)
                content = await call_llm(client, prompt, llm_config)
                data = extract_json(content)
                validated = DPOSampleCWithSkip(**data)

                if validated.skip:
                    return None

                if not validated.chosen or not validated.preference_reason:
                    raise ValueError("skip=false 但缺少 chosen 或 preference_reason")

                return {
                    "task_id": task["task_id"],
                    "task_type": "C",
                    "domain": "movie",
                    "input": {"instruction": pair["text"]},
                    "chosen": validated.chosen.model_dump(),
                    "rejected": {
                        "style": "gremlin",
                        "code": pair["gremlin"],
                    },
                    "preference_reason": validated.preference_reason,
                }
            except (json.JSONDecodeError, ValueError, KeyError, ValidationError):
                if attempt < max_retries - 1:
                    continue
                return _error_result(task["task_id"], "C", f"C 类失败(重试{max_retries}次)")
            except Exception as e:
                return _error_result(task["task_id"], "C", f"C 类异常: {e}")


def _error_result(task_id: str, task_type: str, error: str) -> dict:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "domain": "movie",
        "_error": error,
    }


# ---- 任务准备 ----


def prepare_tasks(classified: dict, num_a: int, num_b: int) -> List[dict]:
    """准备所有任务。"""
    tasks = []
    task_counter = 0

    short_pairs = classified["short"]
    long_pairs = classified["long"]
    medium_pairs = classified["medium"]

    # A 类：从 short 中选取相关组
    for i in range(num_a):
        n = random.randint(2, 5)
        group = select_related_group(short_pairs, n)
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_A_{task_counter:04d}",
                "type": "A",
                "pairs": group,
            }
        )

    # B 类：从 short + medium 中选单条
    b_pool = short_pairs + medium_pairs
    b_selected = random.sample(b_pool, min(num_b, len(b_pool)))
    for pair in b_selected:
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_B_{task_counter:04d}",
                "type": "B",
                "pair": pair,
            }
        )

    # C 类：所有 long 链都尝试
    for pair in long_pairs:
        task_counter += 1
        tasks.append(
            {
                "task_id": f"pref_C_{task_counter:04d}",
                "type": "C",
                "pair": pair,
            }
        )

    random.shuffle(tasks)
    return tasks


# ---- 流水线并发 ----


async def run_pipeline(
    tasks: List[dict],
    llm_config: dict,
    output_path: str,
    input_path: str,
    save_interval: int = 50,
) -> List[dict]:
    """流水线并发处理所有任务"""
    req_timeout = llm_config.get("timeout", 40)
    client = AsyncOpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
        timeout=req_timeout,
    )

    semaphore = asyncio.Semaphore(llm_config["max_concurrency"])

    handler_map = {"A": process_type_a, "B": process_type_b, "C": process_type_c}

    pending_tasks = {}
    for task in tasks:
        handler = handler_map[task["type"]]
        coro = handler(client, task, semaphore, llm_config)
        async_task = asyncio.create_task(coro)
        pending_tasks[async_task] = task["task_id"]

    pending = set(pending_tasks.keys())
    results = []
    completed = 0
    last_save = 0
    skipped = 0
    start_time = time.time()

    print(f"  共 {len(tasks)} 个任务")
    print(f"  并发数: {llm_config['max_concurrency']}")
    print(f"  每 {save_interval} 条保存一次")

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

        for task in done:
            result = task.result()
            completed += 1

            if result is None:
                skipped += 1
            else:
                results.append(result)

            elapsed = time.time() - start_time
            speed = completed / elapsed if elapsed > 0 else 0
            valid = len([r for r in results if "_error" not in r])
            print(
                f"\r  进度: {completed}/{len(tasks)} (有效:{valid} 跳过:{skipped} {speed:.1f}条/秒)",
                end="",
                flush=True,
            )

            if len(results) - last_save >= save_interval and results:
                _incremental_save(results, output_path, input_path, elapsed)
                last_save = len(results)
                print(f" [已保存]", end="", flush=True)

    print()
    return results


# ---- 保存 ----


def _incremental_save(results: List[dict], output_path: str, input_path: str, elapsed: float):
    success = [r for r in results if "_error" not in r]
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_samples": len(success),
            "error_count": len(errors),
            "type_distribution": type_counts,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "in_progress",
        },
        "samples": success,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def save_results(results: List[dict], output_path: str, input_path: str, elapsed: float):
    success = [r for r in results if "_error" not in r]
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_samples": len(success),
            "error_count": len(errors),
            "type_distribution": type_counts,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "completed",
        },
        "samples": success,
        "errors": errors,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


# ---- 主函数 ----


def main():
    parser = argparse.ArgumentParser(description="生成 DPO 偏好训练数据 (Groovy vs Gremlin)")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--input", default=None, help="text2gremlin 数据文件")
    parser.add_argument("--output", default=None, help="输出文件路径")
    parser.add_argument("--num-a", type=int, default=200, help="A 类任务数量（多任务组合）")
    parser.add_argument("--num-b", type=int, default=None, help="B 类任务数量（默认为 A 的 1/3）")
    args = parser.parse_args()

    config = load_config(args.config)
    llm_config = get_llm_config(config)
    output_dir = config.get("output_dir", "output")

    # 加载数据
    input_path = args.input or find_latest_pairs(output_dir)
    if not input_path or not os.path.exists(input_path):
        print("❌ 未找到 text2gremlin 数据文件")
        sys.exit(1)

    pairs = load_pairs(input_path)
    if not pairs:
        print(f"❌ 数据文件为空: {input_path}")
        sys.exit(1)

    # 分类
    classified = classify_pairs(pairs)
    print(f"📊 数据分类:")
    print(f"  短查询 (≤5步): {len(classified['short'])} 条 → A/B 类")
    print(f"  中等查询 (6-8步): {len(classified['medium'])} 条 → B 类")
    print(f"  长查询 (>8步): {len(classified['long'])} 条 → C 类")

    num_a = args.num_a
    num_b = args.num_b if args.num_b is not None else max(1, num_a // 3)
    num_c = len(classified["long"])

    tasks = prepare_tasks(classified, num_a, num_b)

    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pref_dir = os.path.join(output_dir, "preference_data")
        output_path = os.path.join(pref_dir, f"dpo_data_{timestamp}.json")

    print("\n" + "=" * 60)
    print("🚀 DPO 偏好数据生成器")
    print("=" * 60)
    print(f"\n📋 配置:")
    print(f"  输入文件: {input_path}")
    print(f"  输出文件: {output_path}")
    print(f"  模型: {llm_config['model']}")
    print(f"  并发数: {llm_config['max_concurrency']}")
    print(f"  最大重试: {llm_config['max_retries']}")
    print(f"  保存间隔: 每 {llm_config['save_interval']} 条")
    print(f"\n📊 任务分布:")
    print(f"  A 类 (多任务组合): {num_a}")
    print(f"  B 类 (单任务): {num_b}")
    print(f"  C 类 (长链拆解): {num_c}")
    print(f"  总计: {len(tasks)}")
    print("-" * 60)

    start_time = time.time()
    results = asyncio.run(
        run_pipeline(
            tasks,
            llm_config,
            output_path,
            input_path,
            save_interval=llm_config["save_interval"],
        )
    )
    elapsed = time.time() - start_time

    save_results(results, output_path, input_path, elapsed)

    success = [r for r in results if "_error" not in r]
    errors = [r for r in results if "_error" in r]

    type_counts = {}
    for r in success:
        t = r.get("task_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1

    print("\n" + "=" * 60)
    print("✅ DPO 数据生成完成")
    print("=" * 60)
    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  有效样本: {len(success)}，失败: {len(errors)}")
    print(f"  类型分布: {type_counts}")
    print(f"  吞吐量: {len(results) / elapsed:.2f} 条/秒" if elapsed > 0 else "")
    print(f"\n💾 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
