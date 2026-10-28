# medication-api-tests

针对 [medication-reminder-backend](https://github.com/Ricardo23178/medication-reminder-backend) 的接口自动化测试套件。

**141 条用例，覆盖鉴权、药品档案、用药计划状态机、提醒确认闭环、家属协同权限隔离、用药统计。**
用 pytest + requests 写成，数据与脚本分离，一条命令跑完并给出可读结果。

```
140 passed, 1 xfailed in 19.48s
```

---

## 这个仓库解决什么问题

毕设后端有 11 个 Controller、40 多个接口。改一处逻辑（比如计划改版后任务快照要重新生成），
受影响的接口分布在四五个模块里，手工用 Apifox 一个个点，既点不全也记不住上次点过什么。

这套用例把「改完之后哪些地方可能坏」固化成可重复执行的代码：

- 每次改接口先跑一遍，**回归成本从半小时降到 20 秒**；
- 断言写在代码里，比「我记得这个接口应该返回 403」可靠；
- 越权、幂等、状态机这类**看不见的边界**，靠人点页面基本测不出来，只能靠用例锁住。

它测的是被测服务（medication-backend），不是替它写单元测试——两者互补，不重叠。

---

## 覆盖范围

| 测试文件 | 关注点 | 条数 |
|---|---|---|
| `test_health.py` | 服务存活、数据库真实连通 | 3 |
| `test_auth.py` | 注册/登录、账号唯一、**拒绝自选角色提权**、登录失败不泄露账号是否存在 | 20 |
| `test_auth_guard.py` | 未登录 401、伪造 token、普通用户访问管理端 403 | 20 |
| `test_medicine_crud.py` | 药品增删改查、字段边界、**横向越权读写改删** | 22 |
| `test_plan_lifecycle.py` | 计划创建校验、暂停/恢复状态机、改版递增、删除、跨用户操作 | 18 |
| `test_reminder_confirm.py` | 今日任务按需生成、确认幂等、稍后/跳过、确认窗口、时间点边界 | 25 |
| `test_family_permission.py` | 邀请码绑定、授权范围校验、解绑撤销、绑定前后权限差异 | 22 |
| `test_statistics.py` | 日历区间、**统计口径恒等式**、完成率闭环、数据隔离 | 11 |

合计 141 条（含参数化展开）。

**几条值得单独说的用例：**

- `test_register_cannot_escalate_to_admin`：请求体里多塞一个 `role: ADMIN` 不会生效。
- `test_login_wrong_password_does_not_leak_which_part_is_wrong`：密码错和账号不存在必须返回同一句话。
- `test_confirm_is_idempotent`：重复确认不产生第二条服药记录，也不报错。
- `test_counters_obey_named_invariant`：把统计口径的恒等式写成断言，算法被人改动会立刻变红。
- `test_owner_unbind_revokes_family_access`：解绑后家属连关系记录都查不到。

---

## 三步跑起来

```bash
# 1) 装依赖
pip install -r requirements.txt

# 2) 重建一次性测试库（不会碰你的开发库，库名必须带 _test）
cp .env.example .env      # 填入 MySQL 账号密码
python scripts/prepare_db.py

# 3) 用测试库启动被测服务（另开一个终端，在 medication-backend 目录下）
export DB_URL='jdbc:mysql://127.0.0.1:3306/medication_api_test?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai'
export DB_PASSWORD='你的MySQL密码'
./mvnw spring-boot:run

# 4) 跑测试
pytest
```

只需要改 `pytest` 一个命令。加 `-v` 看每条用例名，`-x` 遇错即停，`-k 关键词` 只跑某组。

---

## 三条设计取舍

### 1. 每个用例用新注册的账号，不清理数据库

用例之间不共享数据，也就不依赖执行顺序、不需要「跑前清库」。
代价是会留下不少测试账号——但库本身是一次性的，`prepare_db.py` 重建时一把清掉。
比「共享一个测试账号 + 逐个删数据」的写法稳得多：后者一旦某步失败，脏数据会污染后续所有用例。

### 2. 业务错误断言 `body.code`，鉴权错误断言 HTTP 状态码

这个项目有意让业务错误保持 **HTTP 200**，把成败放在响应体的 `code` 里（前端只判断 `body.code`）；
只有拦截器层面的鉴权失败才真的返回 401/403。两种断言的工具分开写在 `api/client.py`，
混用会写出「状态码过了、其实被拦在门外」的假通过。

### 3. 提醒时间点一律取「今天稍后」

后端生成当天任务时会跳过早于计划最后修改时间的时间点。
如果用例写死 `08:00`，下午跑的时候今日清单是空的，后面十几条确认用例全部无对象可测。
所以统一用 `future_remind_time()` 计算「现在 + N 分钟」；接近零点无法构造未来时间点时，用例显式 skip 而不是假失败。

---

## 统计口径（答辩会被追问）

```
应完成 shouldCount  = 当天生成的提醒任务数
已服   takenCount   = action=TAKEN 的记录数
跳过   skippedCount = action=SKIPPED 的记录数
未确认 unconfirmed  = should - taken - skipped
稍后   delayedCount = action=DELAYED 的记录数
```

**恒等式：`should == taken + skipped + unconfirmed`，而 `delayed` 是 `unconfirmed` 的子集。**
所以四项加起来会大于「应完成」——这是有意的口径，不是重复计数：
「稍后提醒」代表这一剂还没吃，仍属于未确认，但需要单独展示让家属知道患者点过。

这条口径已经写成断言（`test_counters_obey_named_invariant`），改动算法会立刻暴露。

---

## 已发现的问题

**1. 「稍后提醒」可能缩短确认窗口（已标记 xfail）**

任务原来的确认窗口是「提醒时间 + 120 分钟」。点「稍后 10 分钟」后，
后端把窗口改成「现在 + 10 + 120 分钟」。如果提醒时间本身还在 30 分钟之后，
新窗口比原窗口短了 20 分钟——患者越点「稍后」，可确认时间反而越少。

建议改成取两者较大值：`expireAt = max(原 expireAt, now + delay + 窗口)`。
用例 `test_delay_does_not_shorten_the_confirmation_window` 用 `xfail` 标记了这条，
后端修好后它会变成 XPASS，把标记去掉即可。

**2. `/api/health` 是全项目唯一不套 `Result` 壳的接口**

其余接口都返回 `{code, message, data}`，只有它直接返回 `{status, serverTime, dbVersion, sysUserCount}`。
前端如果统一按 `code` 判断，这个接口需要单独处理。不影响功能，属于一致性瑕疵。

---

## 没有覆盖的部分

写清楚边界比假装全覆盖更有用：

- **超时过期（EXPIRED）**：需要构造「提醒时间已过 + 超出容忍窗口」的任务，
  当前只能靠等待真实时间或直接改库，容易写出不稳定的用例，暂不纳入。
- **管理端业务逻辑**：只测了「普通用户访问返回 403」，管理员的设置、审计、异常处理未覆盖。
- **并发**：幂等用例是串行重复调用，不是真正的并发压测；`FOR UPDATE` 行锁的效果未验证。
- **性能**：不涉及响应时间与压测。
- **通知投递**：站内消息的入队、已读、分页未覆盖。

---

## 目录结构

```
.
├── api/
│   ├── client.py          # HTTP 客户端 + 三类断言工具（ok / expect_error / expect_http）
│   └── support.py         # 唯一账号生成、未来提醒时间点计算
├── conftest.py            # 全局夹具：服务探活、登录身份、药品
├── schema/
│   └── schema.sql         # 测试库结构（从开发库导出）+ 必要配置种子
├── scripts/
│   └── prepare_db.py      # 重建一次性测试库
├── tests/
│   ├── test_health.py
│   ├── test_auth.py
│   ├── test_auth_guard.py
│   ├── test_medicine_crud.py
│   ├── test_plan_lifecycle.py
│   ├── test_reminder_confirm.py
│   ├── test_family_permission.py
│   └── test_statistics.py
├── .env.example
├── pytest.ini
└── requirements.txt
```

---

## 关于被测项目

上游项目：[medication-reminder-backend](https://github.com/Ricardo23178/medication-reminder-backend)（Spring Boot 3 + MyBatis-Plus + MySQL 8 + JWT），
本人独立开发的毕业设计后端。本仓库是它的接口回归测试，两仓分离是为了让后端仓库保持「只有业务代码」的干净结构。

MIT License © 2026 朱思兴
