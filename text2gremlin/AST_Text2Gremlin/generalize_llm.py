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
Gremlin 查询 LLM 翻译脚本

读取 AST 泛化阶段生成的语料库（Gremlin query + 简单描述），
通过 LLM 将其翻译为自然语言问题，生成 (Gremlin, 自然语言问题) 训练对。

用法:
    # 使用默认配置，自动找到最新的泛化结果
    python generalize_llm.py

    # 指定输入文件
    python generalize_llm.py --input output/generated_corpus_20251029_190729.json

    # 指定输出文件
    python generalize_llm.py --input output/generated_corpus.json --output output/llm_translated.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import List, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field



class GremlinTranslation(BaseModel):
    """LLM 翻译结果的结构化输出模型"""
    questions: List[str] = Field(
        description="翻译后的自然语言问题列表",
        min_length=1,
        max_length=10
    )



def load_config(config_path: str = "config.json") -> dict:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_llm_config(config: dict) -> dict:
    """
    获取 LLM 配置。

    所有必需参数必须在 config.json 的 "llm" 字段中正确配置，
    缺少字段或仍为占位符值时抛出 ValueError。
    """
    llm_cfg = config.get("llm")
    if not llm_cfg:
        raise ValueError(
            "config.json 中缺少 'llm' 配置块，请添加以下配置:\n"
            '  "llm": {\n'
            '    "base_url": "http://your-llm-server:port/v1",\n'
            '    "api_key": "your-api-key",\n'
            '    "model": "your-model-name",\n'
            "    ...\n"
            "  }"
        )

    # 必需字段及其占位符值
    required_fields = {
        "base_url": ["your-llm-server"],
        "api_key": ["your-api-key"],
        "model": ["your-model-name"],
    }

    # 检查缺失
    missing = [f for f in required_fields if f not in llm_cfg]
    if missing:
        raise ValueError(
            f"config.json 的 'llm' 配置中缺少必需字段: {missing}\n"
            "请在 config.json 中补充这些字段。"
        )

    # 检查占位符值未修改
    placeholder_fields = []
    for field, placeholders in required_fields.items():
        val = str(llm_cfg.get(field, ""))
        if any(p in val for p in placeholders):
            placeholder_fields.append(field)

    if placeholder_fields:
        details = ", ".join(f'{f}="{llm_cfg[f]}"' for f in placeholder_fields)
        raise ValueError(
            f"config.json 的 'llm' 配置中以下字段仍为占位符，请修改为实际值: "
            f"{placeholder_fields}\n  当前值: {details}"
        )

    return {
        "base_url": llm_cfg["base_url"],
        "api_key": llm_cfg["api_key"],
        "model": llm_cfg["model"],
        "temperature": llm_cfg.get("temperature", 0.7),
        "max_retries": llm_cfg.get("max_retries", 3),
        "max_concurrency": llm_cfg.get("max_concurrency", 20),
        "batch_size": llm_cfg.get("batch_size", 5),
        "num_questions": llm_cfg.get("num_questions", 2),
    }



def find_latest_corpus(output_dir: str = "output") -> Optional[str]:
    """找到 output 目录下最新的泛化结果文件"""
    pattern = os.path.join(output_dir, "generated_corpus_*.json")
    files = sorted(glob(pattern))
    if not files:
        return None
    return files[-1]


def load_corpus(input_path: str) -> List[dict]:
    """加载泛化结果文件，返回 corpus 列表"""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("corpus", [])



def build_translation_prompt(items: List[dict], num_questions: int) -> str:
    """
    构建批量翻译 prompt。

    每次传入 batch_size 条 (gremlin, description)，让 LLM 逐条翻译为自然语言问题。
    """
    items_text = ""
    for i, item in enumerate(items, 1):
        items_text += f"第{i}条:\nGremlin: {item['query']}\n描述: {item['description']}\n\n"

    prompt = f"""你是一个图数据库专家，需要将 Gremlin 查询语句翻译为图数据库使用者可能提出的自然语言问题。

### 任务
我会给你若干条 Gremlin 查询及其简单描述，请你为每条查询生成 {num_questions} 个不同表达方式的中文自然语言问题。
要求：
1. 问题应符合图数据库使用者的口吻，像是用户在向系统提问
2. 每条查询的多个问题之间表达方式要有差异（问句/陈述句/祈使句等）
3. 问题要准确反映 Gremlin 查询的语义，不要遗漏关键信息（如过滤条件、排序、限制数量等）
4. 使用中文，但专有名词（如人名、电影名等数据值）保持原样
5. 句子要自然流畅，不要出现 Gremlin 语法术语

### 输入
{items_text}
### 输出格式
请严格按照以下 JSON 格式输出，results 数组的长度必须与输入条数一致，每个元素的 questions 数组长度为 {num_questions}：
```json
{{
    "results": [
        {{
            "index": 1,
            "questions": ["问题1", "问题2"]
        }},
        {{
            "index": 2,
            "questions": ["问题1", "问题2"]
        }}
    ]
}}
```

### 示例
输入:
第1条:
Gremlin: g.V().hasLabel('person').has('name', 'Tom Hanks').out('acted_in').values('title')
描述: 从图中开始查找所有顶点，过滤出'人'类型的顶点，其'姓名'为'Tom Hanks'，沿'出演'边out方向遍历，获取'标题'属性值

输出:
```json
{{
    "results": [
        {{
            "index": 1,
            "questions": ["Tom Hanks出演过哪些电影？", "查询演员Tom Hanks参演的所有电影的标题。"]
        }}
    ]
}}
```"""

    return prompt



class BatchTranslationItem(BaseModel):
    """单条翻译结果"""
    index: int
    questions: List[str] = Field(min_length=1)


class BatchTranslationResult(BaseModel):
    """批量翻译结果"""
    results: List[BatchTranslationItem] = Field(min_length=1)



async def translate_batch(
    client: AsyncOpenAI,
    items: List[dict],
    semaphore: asyncio.Semaphore,
    llm_config: dict,
    batch_index: int,
) -> List[dict]:
    """
    翻译一个批次的 Gremlin 查询。

    使用无约束解码 + Pydantic 验证 + 重试。

    Returns:
        翻译结果列表，每个元素包含 query, description, questions
    """
    max_retries = llm_config["max_retries"]
    num_questions = llm_config["num_questions"]

    async with semaphore:
        for attempt in range(max_retries):
            try:
                prompt = build_translation_prompt(items, num_questions)

                response = await client.chat.completions.create(
                    model=llm_config["model"],
                    messages=[{"role": "user", "content": prompt}],
                    temperature=llm_config["temperature"],
                )

                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError("LLM 返回内容为空")

                # 提取 JSON（LLM 可能在 ```json ... ``` 中返回）
                json_str = content
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]

                data = json.loads(json_str.strip())

                # Pydantic 验证
                validated = BatchTranslationResult(**data)

                # 组装结果
                results = []
                for i, item in enumerate(items):
                    # 找到对应的翻译结果
                    translation = None
                    for r in validated.results:
                        if r.index == i + 1:
                            translation = r
                            break

                    if translation and translation.questions:
                        results.append({
                            "query": item["query"],
                            "description": item["description"],
                            "questions": translation.questions,
                        })
                    else:
                        # 该条没有翻译结果，用描述兜底
                        results.append({
                            "query": item["query"],
                            "description": item["description"],
                            "questions": [item["description"]],
                        })

                return results

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                if attempt < max_retries - 1:
                    continue
                else:
                    # 重试耗尽，用描述兜底
                    return [
                        {
                            "query": item["query"],
                            "description": item["description"],
                            "questions": [item["description"]],
                            "_error": f"翻译失败(重试{max_retries}次): {str(e)}",
                        }
                        for item in items
                    ]
            except Exception as e:
                # 非预期错误，不重试
                return [
                    {
                        "query": item["query"],
                        "description": item["description"],
                        "questions": [item["description"]],
                        "_error": f"翻译异常: {str(e)}",
                    }
                    for item in items
                ]


async def translate_all(corpus: List[dict], llm_config: dict) -> List[dict]:
    """
    并发翻译所有语料。

    按 batch_size 分批，使用 semaphore 控制并发。
    """
    client = AsyncOpenAI(
        base_url=llm_config["base_url"],
        api_key=llm_config["api_key"],
    )

    semaphore = asyncio.Semaphore(llm_config["max_concurrency"])
    batch_size = llm_config["batch_size"]

    # 分批
    batches = []
    for i in range(0, len(corpus), batch_size):
        batches.append(corpus[i : i + batch_size])

    print(f"  共 {len(corpus)} 条，分为 {len(batches)} 个批次 (batch_size={batch_size})")
    print(f"  并发数: {llm_config['max_concurrency']}，每条生成 {llm_config['num_questions']} 个问题")

    tasks = [
        translate_batch(client, batch, semaphore, llm_config, idx)
        for idx, batch in enumerate(batches)
    ]

    batch_results = await asyncio.gather(*tasks)

    # 展平结果
    all_results = []
    for batch_result in batch_results:
        all_results.extend(batch_result)

    return all_results


# 保存结果 ============

def save_results(results: List[dict], output_path: str, input_path: str, elapsed: float):
    """保存翻译结果"""
    success_count = sum(1 for r in results if "_error" not in r)
    fail_count = len(results) - success_count
    total_questions = sum(len(r["questions"]) for r in results)

    output_data = {
        "metadata": {
            "source_file": input_path,
            "total_queries": len(results),
            "total_questions": total_questions,
            "success_count": success_count,
            "fail_count": fail_count,
            "elapsed_seconds": round(elapsed, 2),
            "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "corpus": [],
    }

    for r in results:
        entry = {
            "query": r["query"],
            "description": r["description"],
            "questions": r["questions"],
        }
        if "_error" in r:
            entry["_error"] = r["_error"]
        output_data["corpus"].append(entry)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


# 主函数 ============

def main():
    parser = argparse.ArgumentParser(
        description="将泛化后的 Gremlin 查询通过 LLM 翻译为自然语言问题",
    )
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--input", default=None, help="泛化结果文件路径（不指定则自动找最新的）")
    parser.add_argument("--output", default=None, help="输出文件路径")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)
    llm_config = get_llm_config(config)
    output_dir = config.get("output_dir", "output")

    # 定位输入文件
    input_path = args.input
    if not input_path:
        input_path = find_latest_corpus(output_dir)
        if not input_path:
            print(f"❌ 在 {output_dir}/ 下未找到泛化结果文件 (generated_corpus_*.json)")
            sys.exit(1)

    if not os.path.exists(input_path):
        print(f"❌ 输入文件不存在: {input_path}")
        sys.exit(1)

    # 确定输出文件
    output_path = args.output
    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"llm_translated_{timestamp}.json")

    # 加载语料
    corpus = load_corpus(input_path)
    if not corpus:
        print(f"❌ 输入文件中没有语料数据: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("🚀 Gremlin LLM 翻译器")
    print("=" * 60)
    print(f"\n📋 配置:")
    print(f"  输入文件: {input_path}")
    print(f"  输出文件: {output_path}")
    print(f"  模型: {llm_config['model']}")
    print(f"  并发数: {llm_config['max_concurrency']}")
    print(f"  批次大小: {llm_config['batch_size']}")
    print(f"  每条问题数: {llm_config['num_questions']}")
    print(f"  最大重试: {llm_config['max_retries']}")
    print(f"\n  语料条数: {len(corpus)}")
    print("-" * 60)

    # 执行翻译
    start_time = time.time()
    results = asyncio.run(translate_all(corpus, llm_config))
    elapsed = time.time() - start_time

    # 保存结果
    save_results(results, output_path, input_path, elapsed)

    # 统计
    success_count = sum(1 for r in results if "_error" not in r)
    fail_count = len(results) - success_count
    total_questions = sum(len(r["questions"]) for r in results)

    print("\n" + "=" * 60)
    print("✅ 翻译完成")
    print("=" * 60)
    print(f"  总耗时: {elapsed:.2f} 秒")
    print(f"  成功: {success_count}，失败: {fail_count}")
    print(f"  生成问题总数: {total_questions}")
    print(f"  吞吐量: {len(results) / elapsed:.2f} 条/秒")
    print(f"\n💾 结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
