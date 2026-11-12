# 合同双时态追溯

同一份合同存两条时间轴，并且两条都按 **开始包含、结束不包含** 的区间处理：

| 轴 | 字段 | 含义 |
|---|---|---|
| 业务有效期 | `[valid_from, valid_to)` | 这条事实在现实世界里何时成立 |
| 系统有效期 | `[recorded_from, recorded_to)` | 系统何时开始、何时不再把它当作当前认知 |

查询时把两个时刻独立给出：**业务日期**决定"看哪一天的事实"，**查询时点**决定"用哪一版认知回答"。
所以三月生效、四月才录入更正的合同，在"查三月"时可以分别看到四月更正前后两种答案。

## 运行

```bash
./run.sh                # 首次会自动建 venv、装前端依赖、灌演示数据
# API  http://127.0.0.1:8000/docs
# UI   http://127.0.0.1:5173
```

手动分别启动：

```bash
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn pytest httpx
.venv/bin/python -m app.seed                     # 灌入四个演示场景
.venv/bin/python -m uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
.venv/bin/python -m pytest tests -q              # 30 个测试
```

## 更正语义

- 更正**只替换它点名的那段业务区间**；同一版本两侧未被点名的内容原样保留，作为新的"分割行"继续生效。
- 旧版本不被改写：只在系统轴上被置为"不再作为当前认知"（`recorded_to` 变成更正时刻）。
  因此**过去查询时点看到的版本不变**——在更正时刻之前查询，仍旧命中原来那行。
- 每次更正都带着**基准版本 id**（用户打开表单时看到的当前版本）。提交时在同一个
  `BEGIN IMMEDIATE` 事务里检查该版本是否仍然开放；已被别的操作关闭就整批 409，一行都不写。
- **同一请求内的区间互相重叠**、区间为空、越出基准的业务区间、整批无字段变更，都会让整批失败。
- **请求编号幂等**：同编号 + 同内容重交，直接返回第一次的结果（`replayed: true`，不新增行）；
  同编号 + 不同内容，返回 409 `request_id_reused`。
- **恢复旧值**不是删除历史，而是再提交一条覆盖同一区间的更正，把值改回去。

存储上不允许第 3 行同编号同内容的重复行；`request_result` 表按 `request_id` 记录请求指纹与响应。

## 演示场景

| 合同 | 场景 | 看点 |
|---|---|---|
| `C-2026-001` | 追溯涨价 | 三月一日生效、四月二日补录 10 万；四月十日追溯改为 12 万。两个查询时点分别是 04-05 与 04-12 |
| `C-2026-002` | 只改中间一段 | 全年 8 万，只把 5/1–7/1 改成 9.5 万并换客户；两侧 8 万保留 |
| `C-2026-003` | 先后覆盖的两次更正 | 第一次改 2/1–4/1；第二次只覆盖其中 2/15–3/1 |
| `C-2026-004` | 同时提交的冲突请求 | 同一基准收到两条更正，先到者生效，后到者整批 409 |

界面四个页签：**时间线与差异**（两条时间线 + 共同切分逐段对照）、**版本账本**（只追加的行 + 请求记录）、
**点查核对**（业务日期 × 查询时点）、**更正与冲突**（提交更正、幂等重交、并发演练、演示数据重置）。

「用上一版的值填充」会把上一条被更正版本的值填进表单，提交后走的是新更正而不是删除。

## API

```
GET  /api/contracts                                  合同列表（当前段 + 请求编号）
GET  /api/contracts/{no}                             全部版本行 + 请求记录
GET  /api/contracts/{no}/view?business_at=&as_of=     点查
GET  /api/contracts/{no}/timeline?business_from=&business_to=&as_of_a=&as_of_b=
POST /api/contracts                                  建首个版本
POST /api/contracts/{no}/corrections                 提交更正批次
GET  /api/demo/scenarios                             场景元数据
POST /api/demo/reset                                 重置演示数据
POST /api/demo/conflict                              并发冲突演练
```

`timeline` 返回两个快照（`snapshot_a` / `snapshot_b`）以及在两者共同切分上的 `diff`；
每条记录都带 `source_request_id`（内容来源请求）与 `request_id`（把它写进系统的那次请求），
两组区间一并给出，可拿任意两个查询时点逐段核对。

`POST /api/contracts` 与更正接口都接受 `X-Recorded-At` 头，用于固定系统时刻（测试与可复现演示）。

## 代码结构

```
app/models.py     区间与版本的数据模型
app/store.py      SQLite 双时态存储、事务、幂等与冲突检查
app/main.py       FastAPI 路由
app/demo.py       演示场景与冲突演练
app/seed.py       固定时刻的种子数据
frontend/src      React 界面（时间线、差异表、版本账本、点查、更正）
tests/test_core.py 30 个测试：边界、切割、覆盖、冲突、幂等、API
```
