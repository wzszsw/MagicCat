# AGENTS.md — MagicCat 开发约定（持续完善）

> 本文件沉淀用户（产品负责人）在迭代中反复强调的方向与偏好，用于指导后续每次改动。
> **每次迭代都应根据新出现的偏好更新本文件**（新增 / 修订条目），让约定随项目一同演进。

## 1. 总体方向

- **对标 Navicat Premium**：布局、导航、交互尽量向 Navicat 看齐，但**不像素级复刻**，以"轻量、稳定、顺手"为准。
- **技术栈**：PySide6 界面 + JPype 内嵌 JVM + JDBC 数据访问。**MySQL / MariaDB 优先**，PostgreSQL 逐步扩展。
- **首发平台**：Windows。

## 2. 功能取舍原则（重要，反复被强调）

- **先做基本/容易实现的功能，做完一块就收**；不做"高级但复杂、容易超范围"的东西。
- 下列 Navicat 功能**明确不做**：
  - 「备份」领域 = Navicat 专属文件格式备份 —— **不做**（但**自研 SQL 文本转储/恢复**保留，那不是专属格式）。
  - 「模型」= ER 模型设计器（QGraphicsScene 自绘）—— 太复杂，**不做**，顶部「模型」按钮已收掉。
  - 「自动运行」—— 计划任务入口已隐藏，「自动运行」按钮已收掉。
  - 「询问 AI」「查询构建工具（查询创建工具/设计查询）」—— 高级功能，**不做**。
  - 「导入向导」「导出向导」—— **不做**（表领域不加这两个菜单项）。
  - 「其它」对 MySQL **几乎无可用项**：MySQL 下「其它」菜单**一项都不给**；PostgreSQL 下才提供「序列」等。
- 顶部工具栏只放**已实现**的功能；未实现的（如 其它/BI）不占位。
- 收掉按钮/入口时，**服务层功能保留**（仅隐藏 UI 入口，不误删逻辑）。

## 3. 界面与交互偏好

- **顶部图标栏 = 功能领域切换器**，不是固定操作工具条；查询操作放在中央查询工作区，不占全局顶栏。
- **中央工作区第 1 页固定「对象」**（不可关闭占位页），它是所有功能领域的**列表态**统一体现：
  `连接 → [database → schema] → 表/视图/实体化视图/函数/触发器/查询/… → 对象`。
  - 对象树选中什么分类，「对象」页就展示什么列表；双击对象 → 在**后面的标签页**打开编辑态。
  - 同一领域「列表态」与「编辑态」各有专属按钮行。
- 「查询」既可在 **database 级**也可在 **schema 级**右键新建（PG），两级菜单都有「新建查询」。
- **同一对象只开一个标签**（Navicat 设定）：重开对象定位到已开标签，用稳定 `tab_key`。
- 连接/对象**加载失败**：弹 `MessageBox` 提示，**树节点折叠**，不把错误当树内容展示；异常文本清理 Java 前缀。
- 连接树展开加载时显示**旋转 loading 动画**（自绘 spinner，结束恢复原图标）。
- 右侧「信息」面板：**选中什么显示什么**（选中对象页行也联动）。
- 顶部「其它」下拉：`aboutToShow` 时**按当前连接实时重建**（PG 含序列、MySQL 空），避免切换事件遗漏。

## 4. 数据访问与方言

- **MySQL：database ≡ schema**（两级即连接→库→分类）；**PostgreSQL：database 与 schema 是两级**（连接→库→schema→分类）。
- **PostgreSQL 元数据尽量用 JDBC 标准 API**（`DatabaseMetaData`），避免手拼方言敏感的 information_schema SQL；MySQL 可走 information_schema 富信息层。
- 标识符/分页语法**按方言**：PG 双引号 + `LIMIT n OFFSET m`，MySQL 反引号 + `LIMIT offset, limit`。
- **限定名 = 每个标识符分别加引号，再以 `.` 连接**：`"schema"."table"`（PG）、`` `schema`.`table` ``（MySQL）。
  **绝不能把整个 `schema.table` 当成一个标识符包进一对引号**（即 `"schema.table"` 或 `` `schema.table` ``），
  否则 PG/MySQL 都报 "relation does not exist / 找不到"。
- **避免 N+1**：循环内不做数据库 I/O；同类信息尽量**一次批查**（用户明确定义 N+1 = 循环内网络 IO）。
- 跨库枚举（如 PG 某库的 schema/对象）需**临时连到目标库**查询。
- 连接配置有 `provider_key`（方言/驱动 key），贯穿 open/test/连接图标/元数据。

## 5. 图标与素材

- **图标来源**：优先使用**自绘**（QPainter，无第三方版权）；或用 **GitHub 开源图标库（devicon，MIT 可商用）**。
  - 用户明确反馈"自绘产品图标难看"→ 改用 **devicon 彩色 logo**（MIT）作为产品连接图标，缺失回退自绘。
  - **引用素材的来源/许可证要留档**（见 `docs/引用素材.md`）。
- 连接图标按 `provider_key` 区分数据库产品（MySQL/PostgreSQL/MariaDB/Oracle/SQL Server…）。

## 6. 日期时间显示约定

- **统一格式**：日期时间一律显示为 `YYYY-MM-DD HH:MM:SS`（空格分隔，本地时区）。
  - 例：`2026-09-04 10:55:08`（与 Navicat 日志 `[2026-09-03 23:29:37.687]` 一致，仅省略毫秒）。
- 数据侧存储可为 UTC ISO（如 `datetime.now(UTC).isoformat(...)`），**展示时**经
  `magiccat/utils/datetime_format.py` 的 `format_datetime()` 转成上述格式（去 `T`、去时区偏移、转本地时区）。
- 所有展示日期时间的入口统一走 `format_datetime()`：对象页「修改日期」列、结果网格单元格等，
  已由 `ObjectBrowseView.load()` 和 `grid.py` 的 `_display_text()` 接入。

## 7. 工程质量

- 类型注解全覆盖；`uv run ruff check .` 必须通过。
- `uv run pytest` 全绿（含真实 MySQL/PostgreSQL 集成；JVM 相关测试避免 faulthandler 误报）。
- **报错统一风格**：错误提示统一用 `QMessageBox` 弹出（`warning`/`critical`），并清理 Java 重复前缀
  （`clean_java_error`）；运行期错误不要只在状态栏/日志里静默带过。表数据/连接/对象加载失败均弹 MessageBox。
- 改 Java 后需重新 `mvn package` 构建 jar（开发态走 `java-bridge/target/`）。
- **打包**（exe + 便携 zip + `--selftest`）：仅在用户**明确要求**时执行；否则只 commit，不打包。
- 提交信息用中文、单引号包裹、避免 PowerShell 花括号/括号被吞的写法；每次改动一个里程碑语义，附修订记录（M编号）。
- 里程碑进度记录在 `docs/MagicCat设计方案.md` 附录 B（持续更新，含回归数）。

## 8. 开发节奏偏好

- **做完一个功能就收尾**，不要顺手展开到未要求的范围。
- 用户在线可随时给方向并**纠偏**；不在线时**保持保守**，不做超范围改动、不碰未闭环功能。
- 改动前若方向不明确，**先小步确认**（AskUser），避免做偏；但确认后放开做。
- 尊重用户"休息/保守"指示，此时不主动推进。

## 9. 里程碑命名

- 用 `M<N>` 递增编号，每个里程碑一句话描述 + 回归数，持续追加到设计方案附录 B。
- 本文件应与 `docs/MagicCat设计方案.md` 附录 B 的里程碑表保持一致。

## 附录 A：Navicat 本地存储探测笔记（参考）

> 本机装有 Navicat Premium 17，以下为实际探测结论，仅作对齐参考，**不必照搬**内部实现。

- **用 SQLite 做本地缓存/历史/索引**：`Documents\Navicat\Premium\profiles\ai_assistant_history.db`
  （完整 SQLite 库，含多表 + FTS 全文搜索 + `utc_time` 字段）；每个连接目录有 `id_cache.db`(-wal/-shm)。
- **连接配置 / 对象树结构 / 查询收藏**存于**注册表**：`HKCU\Software\PremiumSoft\Navicat\Servers\<conn>\...`
  （含 Profiles / Schemas / TableView / Columns / Query 等键）。
- **查询 SQL 内容**存为 `.sql` 文件：`Documents\Navicat\MySQL\Servers\<conn>\<schema>\<name>.sql`。
- **日志**：`Documents\Navicat\Premium\logs\history.log`，每条形如
  `[2026-09-03 23:29:37.687][localhost_3306][...][MYSQL][]`（即 `YYYY-MM-DD HH:MM:SS.mmm`）。
- 结论：Navicat 对"简单数据/缓存/历史"确实用 **SQLite**；配置多为注册表/JSON；SQL 文件用文件系统。
  我们当前用 `profiles.json`(DPAPI) / `queries/*.json` / `history.json` 的方式可保留，
  若需对齐可将"查询历史/最近使用"等改存 SQLite（视后续需求，不强制）。
