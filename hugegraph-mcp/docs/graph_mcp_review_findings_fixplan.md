# HugeGraph MCP Review Findings Fix Plan

本文档基于 `graph-mcp` 分支近期提交（`ae85315` schema/pytest marker 修复、`f2ccdab` schema 校验加固、`c76770f` edge id URL 编码修复、`f8902ea` 真实 edge id 测试、`d807e03` confirm workflow 加固）之后的一次代码评审，记录发现的问题、根因、修复方案和验收标准。

所有行号基于评审时读取的当前代码状态（`graph-mcp` HEAD = `d807e03`），与评审原始描述基本一致，个别函数起止行有 1-3 行的自然漂移，已在下文更新为准确值。

本文档只给修复方案，不改动任何源代码。

## 0. 问题总览

| 优先级 | 问题 | 影响文件 |
| --- | --- | --- |
| P1 | schema 校验存在遗漏分支，非法 `id_strategy`/枚举字段/标识符字段能穿透 dry-run 拿到 `plan_hash`，apply 阶段才失败 | `hugegraph_mcp/tools/manage_schema.py` |
| P2 | 响应脱敏正则覆盖不全，HTTP header、Python dict repr、无分隔符裸文本三种真实敏感信息载体不脱敏 | `hugegraph_mcp/envelope.py` |
| 次要-1 | `_id_dedupe_key` 对混合 key 类型 dict 输入抛裸 `TypeError`，违反 envelope 契约 | `hugegraph_mcp/tools/query_graph_data.py` |
| 次要-2 | `format_vertex_id_path` 与 `format_edge_id_path` 序列化语义不对称，无文档说明设计意图 | `hugegraph-python-client/src/pyhugegraph/utils/id_format.py` |

## 1. P1（阻塞）：schema 校验遗漏分支导致 dry-run 对必失败操作发 plan_hash

### 1.1 问题描述

**位置 1：`id_strategy` 校验只在精确匹配 `"PRIMARY_KEY"` 时触发**

`hugegraph_mcp/tools/manage_schema.py:215-224`（`_validate_vertex_primary_keys` 函数头部）：

```python
def _validate_vertex_primary_keys(
    *,
    idx: int,
    operation: dict[str, Any],
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    id_strategy = str(operation.get("id_strategy", "PRIMARY_KEY")).upper()
    if id_strategy != "PRIMARY_KEY":
        return
```

只有当 `id_strategy` 恰好等于 `"PRIMARY_KEY"` 时才继续校验 `primary_keys` 必填。任何其他取值——包括拼写错误（`"Primarykey"`、`"PRIMARY_KEYS"`）、非法枚举（`"FOO"`）、带空格（`"PRIMARY_KEY "`，`.upper()` 不会去除空格）——都会在这一行直接 `return`，被当作"非 PRIMARY_KEY 策略，不需要校验 primary_keys"处理，函数直接放行。

而 apply 阶段的 `_apply_vertex_label_options`（`hugegraph_mcp/tools/manage_schema.py:876-887`）：

```python
def _apply_vertex_label_options(builder, operation: dict[str, Any]) -> None:
    id_strategy = str(operation.get("id_strategy", "PRIMARY_KEY")).upper()
    id_strategy_methods = {
        "PRIMARY_KEY": "usePrimaryKeyId",
        "CUSTOMIZE_STRING": "useCustomizeStringId",
        "CUSTOMIZE_NUMBER": "useCustomizeNumberId",
        "AUTOMATIC": "useAutomaticId",
    }
    method_name = id_strategy_methods.get(id_strategy)
    if method_name is None:
        raise ValueError(f"Unsupported vertex label id_strategy: {id_strategy}")
    getattr(builder, method_name)()
```

对 `id_strategy` 做严格枚举查表，任何不在 `id_strategy_methods` 四个键里的值都会 `raise ValueError`。

结果：`id_strategy="FOO"` 这样的非法输入，在 `validate_schema_operations` / `dry_run_schema_operations` 阶段被当作"非 PRIMARY_KEY，跳过 primary_keys 检查"直接放行，`dry_run` 返回 `valid=true` 并附带 `plan_hash`；到 `apply` 阶段调用 `_apply_vertex_label_options` 才抛 `ValueError`。

**位置 2：`validate_schema_operations` 对标识符字段和枚举字段的前置校验缺失**

`hugegraph_mcp/tools/manage_schema.py:407-421`（必填字段检查，位于 `validate_schema_operations` 内）：

```python
for field in REQUIRED_FIELDS[op_type]:
    if field not in operation or operation[field] in (None, ""):
        errors.append(
            _validation_error(
                idx,
                operation,
                f"missing required field: {field}",
                f"Add {field} to the {op_type} operation.",
            )
        )
if any(
    field not in operation or operation[field] in (None, "")
    for field in REQUIRED_FIELDS[op_type]
):
    continue
```

`REQUIRED_FIELDS`（`manage_schema.py:59-64`）覆盖 `name`、`source_label`、`target_label`、`base_label` 等标识符字段，但检查逻辑只判断 `field not in operation or operation[field] in (None, "")`——即只检查"键不存在"或"值恰好是 `None` 或空字符串 `""`"。这意味着：

- 传入 `name=123`（int）、`name=[]`（list）、`name=True`（bool）：这些值都不在 `(None, "")` 集合里，判断为"已提供"，直接放行，不会报 `missing required field`。后续 `name in live_vertex_labels` 之类的集合成员判断在类型不匹配时静默返回 `False`，不会报错，直接进入 `available_vertex_labels.add(name)`（如 `manage_schema.py:539-542`），把非字符串值当作合法名字加入"本批次已创建"集合。
- 传入 `name="   "`（纯空格字符串）：不在 `(None, "")` 里，同样放行，成为一个视觉上是空白、实际是非空字符串的 schema 对象名字。

对枚举字段（`data_type`、`cardinality`、`aggregate_type`、`id_strategy`、`frequency`）则完全没有出现在 `validate_schema_operations` 的任何校验分支中——除了上面提到的 `id_strategy` 半成品校验外，`data_type`、`cardinality`、`aggregate_type`（property key 相关）和 `frequency`（edge label 相关）在 validate 阶段没有任何检查。这些值全部推迟到 apply 阶段，通过各自的查表在 `_apply_property_key_options`（`manage_schema.py:828-873`）和 `_apply_edge_label_options`（`manage_schema.py:897-914`）里报错：

- `data_type` 不在 `data_type_methods`（`manage_schema.py:830-843`）→ apply 阶段 `ValueError`。
- `cardinality` 不在 `cardinality_methods`（`manage_schema.py:849-857`）→ apply 阶段 `ValueError`。
- `aggregate_type` 提供但不在 `aggregate_methods`（`manage_schema.py:860-873`）→ apply 阶段 `ValueError`。
- `frequency` 提供但不是 `"SINGLE"`/`"MULTIPLE"`（`manage_schema.py:906-914`）→ apply 阶段 `ValueError`。

注：`create_index_label` 的 `base_type` 字段例外——`validate_schema_operations` 在 `manage_schema.py:494-524` 已经做了 `base_type == "VERTEX"` / `"EDGE"` 的前置分支校验，非法值会在 validate 阶段报 `unsupported base_type for index label`。这部分已经是正确模式，P1 修复应参照这个已有分支的写法，而不是重新发明。

### 1.2 根因

`validate_schema_operations` 的设计意图是"提前复现 apply 阶段所有会失败的检查"，但历史上只对少数字段（`base_type`、`source_label`/`target_label` 的存在性、`primary_keys` 的精确 `PRIMARY_KEY` 分支）做了这种复现，其余枚举字段的校验逻辑只存在于 apply 阶段的查表里，从未被"抽出一份、放到 validate 阶段也跑一次"。这正是本分支自己在 `graph_mcp_review_fix_plan.md` 的 Fix-10 想解决的"dry-run 通过但 apply 失败造成部分写入"问题的同类分支，Fix-10 只填了 `primary_keys` 缺失这一种情况，没有覆盖 `id_strategy` 本身的枚举合法性，也没有覆盖其他枚举字段和标识符字段的类型校验。

### 1.3 修复方案

#### 1.3.1 把 apply 阶段的枚举表提升为模块级常量，validate 和 apply 共享同一份

在 `manage_schema.py` 靠近 `REQUIRED_FIELDS`（第 59 行附近）新增模块级常量，把当前分散在 `_apply_property_key_options`、`_apply_vertex_label_options`、`_apply_edge_label_options` 函数体内的四个局部字典提升为模块级只读映射：

```python
# 提升为模块级常量，validate 和 apply 共用同一份合法值来源，
# 避免两处枚举表分别维护导致漂移。
PROPERTY_KEY_DATA_TYPES = frozenset(
    {"TEXT", "INT", "INTEGER", "LONG", "DOUBLE", "FLOAT",
     "BOOLEAN", "BOOL", "DATE", "BYTE", "BLOB", "OBJECT"}
)
PROPERTY_KEY_CARDINALITIES = frozenset({"SINGLE", "SET", "LIST"})
PROPERTY_KEY_AGGREGATE_TYPES = frozenset({"OLD", "SUM", "MIN", "MAX"})
VERTEX_LABEL_ID_STRATEGIES = frozenset(
    {"PRIMARY_KEY", "CUSTOMIZE_STRING", "CUSTOMIZE_NUMBER", "AUTOMATIC"}
)
EDGE_LABEL_FREQUENCIES = frozenset({"SINGLE", "MULTIPLE"})
```

`_apply_property_key_options`、`_apply_vertex_label_options`、`_apply_edge_label_options` 内部的 `*_methods` 字典（方法名映射）保持不变，只是把"合法值集合"这一层单独提出来给 validate 复用；apply 阶段仍然用完整的 `*_methods` 字典做实际方法分发，两者的 key 集合必须保持一致（可在测试里加一条断言，见 1.5）。

#### 1.3.2 在 `validate_schema_operations` 中新增枚举校验函数，覆盖所有当前遗漏字段

新增一个通用枚举校验 helper，放在 `_validate_property_references` 和 `_validate_vertex_primary_keys` 之间（约第 213 行附近）：

```python
def _validate_enum_field(
    *,
    idx: int,
    operation: dict[str, Any],
    field: str,
    allowed_values: frozenset[str],
    errors: list[ValidationError],
    required: bool,
    default: str | None = None,
) -> str | None:
    """校验枚举字段合法性，返回规范化后的值（大写、trim），非法时追加 error 并返回 None。

    default 非 None 时，字段缺失按 default 处理（复现 apply 阶段的默认值语义，
    例如 id_strategy 缺失按 PRIMARY_KEY 处理，cardinality 缺失按 SINGLE 处理）。
    """
    raw_value = operation.get(field)
    if raw_value in (None, ""):
        if not required:
            return default
        raw_value = default

    if not isinstance(raw_value, str):
        errors.append(_validation_error(
            idx, operation,
            f"{field} must be a string, got {type(raw_value).__name__}",
            f"Use one of: {', '.join(sorted(allowed_values))} for {field}.",
        ))
        return None

    normalized = raw_value.strip().upper()
    if normalized not in allowed_values:
        errors.append(_validation_error(
            idx, operation,
            f"unsupported {field}: {raw_value!r}",
            f"Use one of: {', '.join(sorted(allowed_values))} for {field}.",
        ))
        return None

    return normalized
```

在 `validate_schema_operations` 的主循环里，针对每种 op_type 调用这个 helper：

- **`create_property_key`** 分支（`manage_schema.py:424-432` 附近，`op_type == "create_property_key"` 的 if 块内）新增：
  - `_validate_enum_field(field="data_type", allowed_values=PROPERTY_KEY_DATA_TYPES, required=True, default="TEXT")`
  - `_validate_enum_field(field="cardinality", allowed_values=PROPERTY_KEY_CARDINALITIES, required=False, default="SINGLE")`
  - 如果 `operation.get("aggregate_type")` 非空，再调用 `_validate_enum_field(field="aggregate_type", allowed_values=PROPERTY_KEY_AGGREGATE_TYPES, required=False)`（`aggregate_type` 本身是可选字段，只在提供时校验合法性，不提供不报错——对齐 apply 阶段 `if aggregate_type:` 的可选语义）。

  注：`data_type` 已经在 `REQUIRED_FIELDS["create_property_key"]` 里被判断"非空"，这里新增的是"值必须在合法枚举内"这一层，两者不冲突，做的是不同的检查。

- **`create_vertex_label`** 分支（`manage_schema.py:433-455` 附近）：在调用 `_validate_vertex_primary_keys` 之前，先调用：
  - `id_strategy = _validate_enum_field(field="id_strategy", allowed_values=VERTEX_LABEL_ID_STRATEGIES, required=False, default="PRIMARY_KEY")`
  - 如果 `id_strategy is None`（校验失败，已经追加了 error），跳过后续 `_validate_vertex_primary_keys` 调用，避免同一个非法输入被 `_validate_vertex_primary_keys` 内部 `str(...).upper()` 重新解析一遍产生第二条容易让人误解的 error（`_validate_vertex_primary_keys` 内部原有的 `str(operation.get("id_strategy", "PRIMARY_KEY")).upper()` 这行判断逻辑可以删除，改为直接接收上面已经规范化好的 `id_strategy` 参数，见 1.3.3）。

- **`create_edge_label`** 分支（`manage_schema.py:456-483` 附近）新增：
  - 如果 `operation.get("frequency")` 非空，调用 `_validate_enum_field(field="frequency", allowed_values=EDGE_LABEL_FREQUENCIES, required=False)`（`frequency` 同样是可选字段，不提供不报错）。

#### 1.3.3 修正 `_validate_vertex_primary_keys` 的 `id_strategy` 分支判断逻辑

`_validate_vertex_primary_keys`（`manage_schema.py:215-299`）当前独立重新解析 `id_strategy`，与 1.3.2 新增的枚举校验存在潜在的双重解析问题。修复方式：把已经校验、规范化过的 `id_strategy` 值通过参数传入，函数体不再自己从 `operation` 里重新取值：

```python
def _validate_vertex_primary_keys(
    *,
    idx: int,
    operation: dict[str, Any],
    id_strategy: str | None,  # 新增参数：由调用方传入已规范化的枚举值（可能为 None，表示上一步枚举校验已失败）
    property_keys: set[str],
    errors: list[ValidationError],
) -> None:
    if id_strategy is None:
        # id_strategy 本身非法，已经在枚举校验里报过错，
        # 不再对 primary_keys 做二次判断，避免同一处输入报两条无关的 error。
        return
    if id_strategy != "PRIMARY_KEY":
        return
    # ... 后续 primary_keys 非空/类型/引用校验逻辑不变 ...
```

调用处（`manage_schema.py:450-455` 附近）相应调整为先取 `_validate_enum_field` 的返回值，再传给 `_validate_vertex_primary_keys`：

```python
id_strategy = _validate_enum_field(
    idx=idx, operation=operation, field="id_strategy",
    allowed_values=VERTEX_LABEL_ID_STRATEGIES, errors=errors,
    required=False, default="PRIMARY_KEY",
)
_validate_vertex_primary_keys(
    idx=idx, operation=operation, id_strategy=id_strategy,
    property_keys=available_property_keys, errors=errors,
)
```

`_validation_warnings`（`manage_schema.py:316-330`）里同样有一段独立的 `id_strategy = str(operation.get("id_strategy", "PRIMARY_KEY")).upper()` 解析逻辑，用于判断"非 PRIMARY_KEY 且无 primary_keys"时给 warning。这段属于 warning（非阻塞），本次 P1 修复不强制改动，但建议同批顺手把它也换成调用同一个 `_validate_enum_field` 的规范化结果（避免全模块出现第三份重复的 `id_strategy` 解析逻辑）；如果不改，需在文档里注明这处已知的、影响范围仅限 warning 文案的重复解析，不影响 valid/plan_hash 的正确性。

#### 1.3.4 新增标识符字段类型校验：`name`/`source_label`/`target_label`/`base_label`

在 `REQUIRED_FIELDS` 必填检查之后（`manage_schema.py:407-421` 之后，紧接着原有的 `name = operation.get("name")` 那一行之前），新增一个统一的标识符字符串校验：

```python
IDENTIFIER_FIELDS = {
    "create_property_key": ("name",),
    "create_vertex_label": ("name",),
    "create_edge_label": ("name", "source_label", "target_label"),
    "create_index_label": ("name", "base_label"),
}


def _validate_identifier_field(
    *, idx: int, operation: dict[str, Any], field: str, errors: list[ValidationError],
) -> bool:
    """校验标识符字段必须是 str 且 strip 后非空。返回是否通过。"""
    value = operation.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(_validation_error(
            idx, operation,
            f"{field} must be a non-empty string, got {value!r}",
            f"Provide {field} as a non-empty string identifier.",
        ))
        return False
    return True
```

在主循环里，对每个 `op_type` 已经通过 `REQUIRED_FIELDS` 存在性检查之后，立即调用：

```python
identifier_ok = all(
    _validate_identifier_field(idx=idx, operation=operation, field=field, errors=errors)
    for field in IDENTIFIER_FIELDS.get(op_type, ())
)
if not identifier_ok:
    continue  # 标识符非法，跳过后续依赖 name/label 做集合成员判断的逻辑
```

这一步补上"类型必须是 str"和"strip 后非空"两层，覆盖评审提到的 `name=123`、`name=[]`、`name="   "` 这几类当前能穿透 `(None, "")` 检查的输入。放在 `REQUIRED_FIELDS` 检查之后、`name in live_vertex_labels` 之类判断之前，确保非字符串或空白字符串不会进入后续 `available_vertex_labels.add(name)`（`manage_schema.py:539-542`）这样的集合操作。

### 1.4 验收标准

1. 对 `create_vertex_label` 操作，`id_strategy` 取以下任意非法值时，`manage_schema(mode="dry_run", ...)` 必须返回 `valid=false`，且返回体中**不包含** `plan_hash` 字段（当前 `dry_run_schema_operations` 在 `validation["valid"]` 为 `False` 时会直接 `return validation`，不会走到生成 `plan_hash` 的分支——修复后只需确保这些非法值确实被判定为 `invalid`，`plan_hash` 缺失是既有代码路径的自然结果，不需要额外改动）：
   - `id_strategy="FOO"`（不存在的枚举值）
   - `id_strategy="Primary_key"`（大小写不一致——当前实现虽然会 `.upper()` 规范化，但拼写错误如 `"Primarykey"` 无空格分隔仍应判定非法）
   - `id_strategy="PRIMARY_KEY "`（带尾部空格）
   - `id_strategy=123`（非字符串类型）
2. 对 `create_property_key` 操作，`data_type` 取 `"FOOBAR"` 或非字符串类型时，`dry_run` 返回 `valid=false`，不含 `plan_hash`。
3. 对 `create_property_key` 操作，`cardinality` 取非法值（如 `"MANY"`）时，`dry_run` 返回 `valid=false`。
4. 对 `create_property_key` 操作，`aggregate_type` 提供但取非法值（如 `"AVG"`）时，`dry_run` 返回 `valid=false`；`aggregate_type` 不提供时不报错。
5. 对 `create_edge_label` 操作，`frequency` 提供但取非法值（如 `"ONCE"`）时，`dry_run` 返回 `valid=false`；`frequency` 不提供时不报错。
6. 对任意 `create_*` 操作，`name` 取非字符串（如 `123`、`[]`、`true`）或纯空白字符串（如 `"   "`）时，`dry_run` 返回 `valid=false`。
7. 对 `create_edge_label` 操作，`source_label`/`target_label` 取非字符串或纯空白字符串时，`dry_run` 返回 `valid=false`。
8. 对 `create_index_label` 操作，`base_label` 取非字符串或纯空白字符串时，`dry_run` 返回 `valid=false`。
9. 回归验证：所有合法输入（`id_strategy` 四个正确取值、`data_type` 十二个正确取值、`cardinality` 三个正确取值、`frequency` 两个正确取值或不提供）在 `dry_run` 阶段仍然返回 `valid=true` 并附带 `plan_hash`，不能因为新增校验误伤合法路径。
10. 回归验证：`create_index_label` 的 `base_type` 校验行为保持不变（`manage_schema.py:494-524` 现有逻辑不受影响）。
11. 新增的模块级枚举常量（`PROPERTY_KEY_DATA_TYPES` 等）与对应 `*_methods` 字典（`data_type_methods` 等）的 key 集合完全一致——建议加一条测试直接断言 `set(PROPERTY_KEY_DATA_TYPES) == set(data_type_methods.keys())`，防止未来只改一处导致 validate 和 apply 的合法值集合漂移。

### 1.5 需要新增的测试用例清单（不新增代码，仅列出测试点）

全部添加到 `hugegraph-mcp/tests/test_manage_schema.py`：

- `test_dry_run_rejects_invalid_id_strategy_enum`：`id_strategy="FOO"`，断言 `valid is False` 且响应中无 `plan_hash` 键。
- `test_dry_run_rejects_id_strategy_with_trailing_whitespace`：`id_strategy="PRIMARY_KEY "`，断言 `valid is False`。
- `test_dry_run_rejects_non_string_id_strategy`：`id_strategy=123`，断言 `valid is False`。
- `test_dry_run_accepts_all_valid_id_strategies`：遍历 `PRIMARY_KEY`/`CUSTOMIZE_STRING`/`CUSTOMIZE_NUMBER`/`AUTOMATIC`（`CUSTOMIZE_STRING`/`CUSTOMIZE_NUMBER`/`AUTOMATIC` 不提供 `primary_keys`），断言均 `valid is True` 且含 `plan_hash`。
- `test_dry_run_rejects_invalid_data_type_enum`：`create_property_key` 的 `data_type="FOOBAR"`，断言 `valid is False`。
- `test_dry_run_rejects_invalid_cardinality_enum`：`cardinality="MANY"`，断言 `valid is False`。
- `test_dry_run_rejects_invalid_aggregate_type_when_provided`：`aggregate_type="AVG"`，断言 `valid is False`；对照用例 `aggregate_type` 不提供时应 `valid is True`。
- `test_dry_run_rejects_invalid_edge_frequency_when_provided`：`frequency="ONCE"`，断言 `valid is False`；对照用例 `frequency` 不提供时应 `valid is True`。
- `test_dry_run_rejects_non_string_name`：对 `create_vertex_label`/`create_edge_label`/`create_property_key`/`create_index_label` 四种类型分别传 `name=123`，断言均 `valid is False`。
- `test_dry_run_rejects_blank_name`：`name="   "`，断言 `valid is False`。
- `test_dry_run_rejects_non_string_source_or_target_label`：`create_edge_label` 的 `source_label=123` 或 `target_label=""`（空格），断言 `valid is False`。
- `test_dry_run_rejects_non_string_base_label`：`create_index_label` 的 `base_label=123`，断言 `valid is False`。
- `test_enum_tables_stay_in_sync_with_apply_methods`：直接在测试文件里断言 `manage_schema_module.PROPERTY_KEY_DATA_TYPES`、`PROPERTY_KEY_CARDINALITIES`、`PROPERTY_KEY_AGGREGATE_TYPES`、`VERTEX_LABEL_ID_STRATEGIES`、`EDGE_LABEL_FREQUENCIES` 分别与 `_apply_property_key_options`/`_apply_vertex_label_options`/`_apply_edge_label_options` 内部对应 `*_methods` 字典的 key 集合相等（可通过 import 内部函数后用 `inspect` 或直接复制常量名断言，具体实现方式留给写测试时决定）。
- `test_invalid_enum_input_never_reaches_apply_stage_error`：构造一个 batch，第一个操作合法（会真实创建成功——需 mock `_apply_one_operation` 或使用现有的 `_schema`/`_vertex_label` fixture 体系），第二个操作 `id_strategy="FOO"`；断言 `mode="dry_run"` 阶段就能拦截（`valid=false`），不需要真正调用 `mode="apply"` 走到 partial 状态（这是复现"部分写入"场景的最小回归用例，确保修复后同一个 batch 不会在 apply 阶段才失败）。

## 2. P2（建议同批修，非阻塞）：`sanitize_for_response` 脱敏正则覆盖不全

### 2.1 问题描述

`hugegraph_mcp/envelope.py:98-115`（`_sanitize_text` 函数）：

```python
def _sanitize_text(value: str) -> str:
    if not _may_contain_sensitive_marker(value):
        return _redact_url_userinfo(value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        redacted = re.sub(
            r'(?i)("?[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)[a-z0-9_-]*"?\s*[:=]\s*)"[^"]*"',
            rf"\1\"{REDACTED_VALUE}\"",
            value,
        )
        redacted = re.sub(
            r"(?i)(api_key|authorization|password|passwd|pwd|secret|token)=([^&\s]+)",
            rf"\1={REDACTED_VALUE}",
            redacted,
        )
        return _redact_url_userinfo(redacted)
    return json.dumps(sanitize_for_response(parsed), ensure_ascii=False)
```

当前两条正则各自只覆盖一种格式：

- 第一条（`manage_schema.py` 无关，此处为 `envelope.py:104-108`）只匹配 **`"key": "value"`**（双引号包裹值，冒号或等号后跟双引号字符串）。
- 第二条（`envelope.py:109-113`）只匹配 **`key=value`**（等号连接，值不含 `&` 或空白，无需引号）。

对以下三种真实格式完全不生效（已用 Python 脚本实测验证，见下）：

1. **HTTP header 打印格式**：`Authorization: Bearer abc123token`（冒号 + 空格，值不加引号）。这是 `requests` 库在打印 `response.request.headers` 或异常信息里附带请求头时最常见的格式，第一条正则要求值被双引号包裹，第二条正则要求 `=` 连接，两者都不匹配"冒号+空格+无引号裸词"这种结构。实测：脱敏前后字符串完全相同，未发生任何替换。
2. **Python dict repr（单引号）**：`{'Authorization': 'Bearer abc123', 'token': 'xyz'}`。这是 Python 对 dict 对象做 `str()`/`repr()` 时的默认输出格式（键值都用单引号），常见于 `requests.exceptions.RequestException` 的 `args` 或 `response.headers` 被直接拼进异常消息的场景。第一条正则的 `"[^"]*"` 只认双引号，对单引号包裹的值不生效。实测：脱敏前后字符串完全相同。
3. **无分隔符裸文本**：`request failed, token abc123 rejected`。这是最容易在自由文本异常消息里出现的形式——没有 `:` 也没有 `=`，敏感词和值之间只有空格。两条正则都要求"敏感词后紧跟冒号或等号"，对这种纯自然语言拼接完全不生效。实测：脱敏前后字符串完全相同。

而 `_may_contain_sensitive_marker`（`envelope.py:118-120`）判断是否需要进入脱敏分支的逻辑（"文本中包含敏感词或包含 `://`"）对上述三种格式都能正确触发（因为 `token`/`authorization` 关键词本身存在），问题不在"是否进入脱敏分支"，而在"进入分支后两条具体正则都不匹配这三种真实结构"。

危害：`requests` 库的异常（如 `requests.exceptions.ConnectionError`、`HTTPError`）在 `str(exc)` 时经常会把请求上下文（包括 headers）序列化进异常消息，如果异常消息最终通过 `envelope_err` 的 `details={"error": str(exc)}` 这类模式（参见 `manage_schema.py:694` 的 `details={"stage": "schema_fetch", "error": str(exc)}`）返回给调用方，上述三种格式的真实 Authorization header 或 token 值会原样出现在 MCP 响应里。

### 2.2 根因

两条正则设计时只考虑了"结构化配置/URL query string"这一类场景（JSON 字段、URL query 参数），没有覆盖"异常消息里的自然语言拼接"和"HTTP/Python 对象的字符串化表示"这两类同样常见、但结构完全不同的敏感信息载体。`_may_contain_sensitive_marker` 的判断逻辑本身是够用的（"关键词打点"策略对三种新格式一样有效），缺口只在于具体替换用的正则模式集合太窄。

### 2.3 修复方案

在现有两条正则之后，追加三条新正则，分别覆盖三种缺口格式。修改位置是 `_sanitize_text` 函数体内 `except json.JSONDecodeError:` 分支（`envelope.py:103-114`）：

```python
except json.JSONDecodeError:
    redacted = re.sub(
        r'(?i)("?[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)[a-z0-9_-]*"?\s*[:=]\s*)"[^"]*"',
        rf"\1\"{REDACTED_VALUE}\"",
        value,
    )
    redacted = re.sub(
        r"(?i)(api_key|authorization|password|passwd|pwd|secret|token)=([^&\s]+)",
        rf"\1={REDACTED_VALUE}",
        redacted,
    )
    # 新增 1：HTTP header 打印格式，冒号+空格分隔，值不加引号，
    # 值本身允许包含空格（如 "Bearer abc123"），直到行尾/逗号/引号结束。
    redacted = re.sub(
        r"(?i)((?:api_key|authorization|password|passwd|pwd|secret|token)\s*:\s*)"
        r"([^,\"'\n]+)",
        rf"\1{REDACTED_VALUE}",
        redacted,
    )
    # 新增 2：Python dict repr，单引号包裹 key 和 value。
    redacted = re.sub(
        r"(?i)('[a-z0-9_-]*(?:api_key|authorization|password|passwd|pwd|secret|token)"
        r"[a-z0-9_-]*'\s*:\s*)'[^']*'",
        rf"\1'{REDACTED_VALUE}'",
        redacted,
    )
    # 新增 3：无分隔符裸文本，敏感词后紧跟一个"值样 token"
    # （允许字母数字、下划线、短横线、点号的连续片段），
    # 敏感词和值之间允许 0 个或多个空格/冒号/等号。
    redacted = re.sub(
        r"(?i)\b(api_key|authorization|password|passwd|pwd|secret|token)"
        r"(\s*[:=]?\s+)([a-z0-9_.\-]{4,})\b",
        rf"\1\2{REDACTED_VALUE}",
        redacted,
    )
    return _redact_url_userinfo(redacted)
```

设计要点说明：

- **新增 1（HTTP header）** 故意不限制值的字符集合（只排除逗号、引号、换行），因为 header 值可能是 `Bearer <token>` 这种带空格的复合值，需要整体脱敏而不是只脱敏 token 部分——否则 `Bearer` 字样保留、真正的 token 值被替换看起来更安全，但如果值格式不是 `Bearer xxx` 而是别的 scheme，遗漏就会发生。整体替换更保守。
- **新增 2（dict repr）** 复用第一条正则（双引号版）的结构，只是把引号符号换成单引号，两条正则模式高度对称，便于维护时同步修改。
- **新增 3（裸文本）** 是最宽泛的一条，刻意加了 `\b`（word boundary）和"值至少 4 个字符”的限制（`{4,}`），避免过度匹配把普通英文单词"token"后面跟的任意短词也脱敏掉（例如 "the token is invalid" 中 "is" 只有2个字符，不会被误判为需要脱敏的值）；同时正则里 `[a-z0-9_.\-]` 不含空格，所以只脱敏紧跟在敏感词后的"一个类 token 片段"，不会像新增1那样吞掉后续整句话——这是三条新正则里唯一一条需要谨慎控制误伤范围的（宽泛正则容易把正常业务文本误判成敏感信息），建议实现时先跑一遍现有测试集全集（`test_error_handling.py`、`test_manage_schema.py` 等所有涉及错误消息拼接的用例）确认没有回归。
- 三条新正则都放在现有两条之后按顺序 `re.sub`，允许对同一段文本连续应用多条规则（例如一段文本同时包含 JSON 格式和裸文本格式的两个不同敏感字段）。

替代方案（如果多条正则的可维护性成为顾虑）：改用一次性的"分隔符无关"策略——先用一条正则统一识别"敏感词 + 紧邻的任意非空白分隔符（`:`/`=`/空格中的 0 个或多个组合）+ 值”，用命名分组一次捕获，而不是分别为四种分隔符风格各写一条正则。这个方案实现更紧凑，但正则本身复杂度更高、调试更难，且需要同时正确处理"值可能带引号也可能不带”的两种子情况，建议只在上面的分步方案在实测中出现明显维护负担时再考虑切换。

### 2.4 验收标准

1. 输入 `"Authorization: Bearer abc123token"`，脱敏后不再包含 `abc123token` 字面值。
2. 输入 `"{'Authorization': 'Bearer abc123', 'token': 'xyz'}"`，脱敏后 `abc123` 和 `xyz` 均被替换为 `REDACTED_VALUE`，dict 的整体结构（花括号、逗号）保持不变。
3. 输入 `"request failed, token abc123 rejected"`，脱敏后 `abc123` 被替换，`request failed,` 和 `rejected` 两段无关文本保持原样不被误删。
4. 回归：现有两种已支持格式（`"api_key": "xxx"` 和 `api_key=xxx`）继续正确脱敏，不因新增正则顺序问题产生双重替换或替换失败。
5. 回归：不包含任何敏感词的普通错误消息（如 `"vertex label already exists: person"`）脱敏前后完全一致，新增的裸文本正则不会误伤正常业务文案。
6. 回归：URL userinfo 脱敏（`_redact_url_userinfo`，`envelope.py:123-124`）逻辑不受影响，仍在所有新增正则之后最后执行一次。

### 2.5 需要新增的测试用例清单（不新增代码，仅列出测试点）

全部添加到 `hugegraph-mcp/tests/test_error_handling.py`（该文件已在 `f2ccdab` 提交中新增，是脱敏/错误映射类测试的现有落点）：

- `test_sanitize_redacts_http_header_format`：输入 `"Authorization: Bearer abc123token"`，断言输出不含 `abc123token`。
- `test_sanitize_redacts_python_dict_repr_format`：输入 `"{'Authorization': 'Bearer abc123', 'token': 'xyz'}"`，断言输出不含 `abc123` 和 `xyz`，且仍是合法可读的类 dict 字符串结构。
- `test_sanitize_redacts_bare_text_format`：输入 `"request failed, token abc123 rejected"`，断言输出不含 `abc123`，且包含 `request failed` 和 `rejected` 字面片段（确认无关文本未被误删）。
- `test_sanitize_preserves_existing_quoted_json_format`：输入现有支持的 `'{"api_key": "sk-xxx"}'` 格式，断言仍正确脱敏（防止新增正则顺序或组合导致回归）。
- `test_sanitize_preserves_existing_query_string_format`：输入现有支持的 `"token=abc123&other=1"` 格式，断言 `token=` 后的值被脱敏，`other=1` 不受影响。
- `test_sanitize_does_not_redact_unrelated_text`：输入不含任何敏感词的普通句子（如 `"vertex label already exists: person"`），断言脱敏前后完全相等。
- `test_sanitize_bare_text_does_not_over_match_short_values`：输入类似 `"the token is invalid"` 的句子（`token` 后紧跟的 `is` 只有 2 个字符），断言 `is` 未被误判为需脱敏的值（验证新增正则 3 的 `{4,}` 长度下限按预期工作，不误伤正常英文短词）。

## 3. 次要问题（可选一并给方案，不强制）

### 3.1 `_id_dedupe_key` 对混合 key 类型 dict 输入抛裸 `TypeError`

**问题描述**

`hugegraph_mcp/tools/query_graph_data.py:424-429`：

```python
def _id_dedupe_key(item: Any, *, target: str) -> str:
    return json.dumps(
        {"target": target, "type": type(item).__name__, "value": item},
        sort_keys=True,
        default=str,
    )
```

被 `_normalize_ids`（`query_graph_data.py:406-421`）在一个 `for` 循环内部直接调用，循环体和调用方（`query_graph_data.py:83`，`operation == "get_by_ids"` 分支）都没有包裹 `try/except`。

已用 Python 3.14 环境实测：当 `item` 是一个混合 key 类型的 dict（如 `{1: "a", "1": "b"}`）时，`json.dumps(..., sort_keys=True)` 在内部尝试对 dict 的 key 排序时会比较 `int` 和 `str`，抛出：

```
TypeError: '<' not supported between instances of 'str' and 'int'
```

这是一个裸 `TypeError`，不会被 `query_graph_data` 函数体内现有的 `try/except Exception as exc: return _query_error(exc)`（`query_graph_data.py:104-105`）捕获——因为 `_normalize_ids` 的调用点（`query_graph_data.py:83`）在这个 `try` 块**之前**执行（`try` 块从 `manager = _graph_manager()` 那一行开始，`normalized_ids = _normalize_ids(...)` 在 `try` 块外）。所以这个 `TypeError` 会直接从 `query_graph_data` 函数抛出，不经过任何 envelope 包装，违反了"所有 MCP 工具通过 envelope_ok/envelope_err 返回一致结构"的契约（`envelope.py:14-17` 模块 docstring 明确写的设计原则）。

**根因**

`_normalize_ids` 的调用被安排在获取 `manager` 和真正发起查询的 `try` 块之外，是因为它属于"输入规范化"步骤，逻辑上被当作和后面的 `_validate_inputs`（已经在 `try` 块外，且自身有完善的返回值式错误处理，不会抛异常）同一类操作。但 `_normalize_ids` 内部调用的 `_id_dedupe_key` 实际上可能因为输入数据本身的结构（如混合类型的 dict key）抛出未预期的异常，这一点在原实现里没有被考虑到。

**修复方案（不新增代码行数结构，只调整既有代码的包裹范围/前置校验方式，二选一）**

**方案 A（推荐）：把 `_normalize_ids` 调用纳入现有 try 块**

把 `query_graph_data.py:82-86` 的 `normalized_ids = ...` 这一行移动到 `query_graph_data.py:89` 的 `try:` 块内部（即 `manager = _graph_manager()` 之前或之后均可，逻辑上放在 `manager = _graph_manager()` 之前更合理，因为不依赖 manager），让现有的 `except Exception as exc: return _query_error(exc)` 自然覆盖到这条路径。这是改动范围最小的方案——不需要新写一个 try/except，只是把已有的一行代码挪到已有 try 块的覆盖范围内。需要确认 `_query_error`（错误映射函数）对一个裸 `TypeError`（不是 HugeGraph 相关异常）能给出合理的 `error_type`（可能会落到默认的 `SERVER_ERROR` 或类似兜底分类，这属于 `error_mapping.py` 的既有兜底行为，不需要为这一种情况新增专门分类，只要不再是裸异常穿透即可）。

**方案 B：在 `_id_dedupe_key` 之前做前置类型校验，提前在 `_validate_inputs` 阶段拦截**

在 `_validate_inputs`（`query_graph_data.py:126-...`）的 `get_by_ids` 分支（现有的 `query_graph_data.py:156-168`，已经在检查 `ids` 是否是非空列表、是否含空值、长度是否超限）里，新增一条对 `ids` 列表内每个元素的类型检查：如果 `target="edge"` 场景允许 dict 作为复合 id 表示（需先确认这一点在当前实现里是否真的是设计意图——如果混合 key 类型的 dict 本身就不是一个当前设计里"允许"的合法输入形态，那么这条校验应该直接拒绝"dict 类型的 id 元素"，而不是只拒绝"key 类型混合"这一种子情况，需要先确认 dict 类型的 id 元素在业务上是否本来就该被支持）。这个方案需要先回答一个业务问题：dict 类型的 id 元素是否是当前 `get_by_ids` 支持的合法输入？如果不是，直接在 `_validate_inputs` 里加"每个 id 元素不能是 dict/list"的类型白名单校验即可,比方案 A 更早拦截、报错信息也更明确（"id 元素类型不支持"，而不是"序列化失败"这种偏技术细节的错误）。如果 dict 本来就是合法输入形态（例如用于表示某种复合 id），则应该采用方案 A，因为方案 B 无法在不改变"允许 dict"这一行为的前提下解决"dict 内部 key 类型混合"这个更细的问题。

由于本次评审未确认 dict 类型 id 元素在业务上是否为设计支持的输入形态，**建议默认采用方案 A**（改动更小、不依赖对这一业务问题的判断，且能覆盖"混合 key 类型 dict"之外任何其他未预见的序列化异常输入），方案 B 作为在确认"dict 不应该是合法 id 元素"之后的加强项。

**验收标准**

- 输入 `ids=[{1: "a", "1": "b"}]` 调用 `query_graph_data(target="vertex", operation="get_by_ids", ids=[...])`，返回值必须是一个合法的 envelope 结构（`ok=False`，`error` 字段非空），不能抛出未捕获的 `TypeError`。
- 回归：现有所有合法 `ids` 输入（字符串、整数、正常结构的 dict）的去重行为不受影响。

**需要新增的测试用例清单**

添加到 `hugegraph-mcp/tests/test_query_graph_data_tool.py`：

- `test_get_by_ids_with_mixed_key_type_dict_returns_envelope_error`：`ids=[{1: "a", "1": "b"}]`，断言返回值是合法 envelope（`ok is False`，包含 `error.type`），不抛异常。
- `test_get_by_ids_dedupe_still_works_for_normal_inputs`：现有正常输入（字符串重复 id）的去重行为回归测试，确认修复没有改变正常路径行为。

### 3.2 `format_vertex_id_path` 与 `format_edge_id_path` 序列化语义不对称

**问题描述**

`hugegraph-python-client/src/pyhugegraph/utils/id_format.py:50-60`：

```python
def format_vertex_id_path(vertex_id, allow_none: bool = False) -> str | None:
    formatted_id = format_vertex_id(vertex_id, allow_none=allow_none)
    if formatted_id is None:
        return None
    return quote(formatted_id, safe="")


def format_edge_id_path(edge_id) -> str:
    if edge_id is None:
        raise ValueError("The edge id can't be None")
    return quote(str(edge_id), safe="")
```

`format_vertex_id_path` 内部先调用 `format_vertex_id`（`id_format.py:27-47`），后者会用 `json.dumps(vertex_id, allow_nan=False)` 把 vertex id 包装成一个 JSON 字符串（例如整数 `123` 会变成字符串 `"123"` 带外层引号，字符串 `"abc"` 会变成 `"\"abc\""` 带转义引号），然后再对这个 JSON 字符串整体做 `quote`。而 `format_edge_id_path` 直接对 `str(edge_id)` 做 `quote`，不经过 `json.dumps` 这一层。

两者的行为差异是有意为之还是遗漏尚不确定——vertex id 需要 `json.dumps` 包装大概率是因为 HugeGraph server 端对 vertex id 的路径参数格式要求本身就是"JSON 字面量字符串"（区分数字型 id 和字符串型 id 需要依赖 JSON 的类型语法，比如 `123` vs `"123"`），而 edge id 在 HugeGraph 里本身就是一个复合字符串（形如 `S1:alice>11>>S2:bob`，参照 `graph_mcp_review_fix_plan.md` Fix-11 提到的真实 edge id 格式），不需要额外的 JSON 类型区分。这个假设合理，但当前代码里没有任何注释说明这一点，容易让后续维护者误以为是"漏了一步 json.dumps 的 bug”而去"修复"它，破坏实际预期行为。

**修复方案**

不改变任何函数行为，只在两个函数各自加一条简短 docstring，说明各自的设计意图和差异原因：

```python
def format_vertex_id_path(vertex_id, allow_none: bool = False) -> str | None:
    """将 vertex id 格式化为 URL path 片段。

    先经过 format_vertex_id 的 json.dumps 包装，
    以 JSON 字面量语法区分数字型 id（如 123）和字符串型 id（如 "123"）——
    HugeGraph server 端按此语法解析 vertex id 的类型，与 edge id 的语义不同。
    """
    formatted_id = format_vertex_id(vertex_id, allow_none=allow_none)
    if formatted_id is None:
        return None
    return quote(formatted_id, safe="")


def format_edge_id_path(edge_id) -> str:
    """将 edge id 格式化为 URL path 片段。

    edge id 本身是 HugeGraph 生成的复合字符串（如 "S1:alice>11>>S2:bob"），
    不需要 JSON 类型区分，直接对字符串形式做 URL 编码。
    """
    if edge_id is None:
        raise ValueError("The edge id can't be None")
    return quote(str(edge_id), safe="")
```

**验收标准**

- 两个函数行为完全不变（这是纯文档补充，无行为改动）。
- docstring 准确反映当前实际实现逻辑，不引入与代码不符的描述。
- 建议在合入前找到当初引入这一差异的提交（`c76770f fix(client): encode edge ids in graph API paths`）确认这确实是有意设计，而不是本文档基于代码结构反推出的合理化解释——如果原作者确认这是遗漏而非设计，应该走单独的行为修复而不是补文档掩盖问题。

（这一条不需要新增测试，因为不改变行为。）

## 4. 修复顺序建议

1. 先做 P1（阻塞项），因为它直接影响 dry-run 的正确性保证，是本分支"防止部分写入"这一安全设计的核心承诺。
2. P2 建议紧跟 P1 同批修，因为改动范围小（只涉及一个函数内的正则表达式），且是真实的信息泄露风险。
3. 次要项 3.1（`_id_dedupe_key` 异常处理）建议一并评估修复方案 A，改动量极小（挪动一行代码位置），性价比高。
4. 次要项 3.2（docstring 补充）优先级最低，可以放到任意一次顺手的小改动里处理，或者单独发一个纯文档 PR。
