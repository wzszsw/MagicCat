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
- **当前连接 = 树跟手（重要，对标 Navicat）**：Navicat **全局无「当前连接选择控件」**（顶栏功能切换器不含连接下拉）。
  当前连接取决于**用户在左侧对象树最近激活的元素**（双击连接/库/表/对象等），该元素所属连接即当前连接，顶部工具栏作用于它。
  - MagicCat：**全局顶栏不放连接下拉**；当前连接由对象树激活（`profile_activated`）驱动。
  - 左侧连接树的连接节点以 JDBC 打开状态区分图标：已打开连接保留彩色产品图标，关闭连接显示灰度图标；连接右键菜单第一项随状态切换为「关闭连接」或「打开连接」。此状态仅限对象树，查询等连接选择下拉始终显示彩色图标。
  - **「查询」领域工作区内部有「当前连接选择」下拉**（连接 + Catalog + Schema），用户可手动切换；
    左侧树的普通选中不改写已打开查询标签，只有“库/模式 → 新建查询”会把右键目标写入新标签。
  - `ObjectExplorer` 选中任意可归属连接的对象 → emit `profile_activated(profile_id)` → `MainWindow._set_current_profile`
    只更新对象浏览领域的当前连接（profile_combo 下拉）+ 库下拉 + 查询列表；已打开的查询标签不随树选中变化。
  - 对象页不显示全局连接下拉；内部树跟手状态仅用于对象列表和新建查询初始化。
    固定“对象”页跟随左树当前连接、database/schema、分类及对象节点更新列表域与上下文；
    跟手同步不得改写或强制切走已打开的查询标签。
    “其它→序列”及序列页刷新/DDL 后重载同样使用对象页最近一次树上下文，不回退到连接初始库。
    查询标签的 `profile_combo` 是其自身连接锚点，`_current_profile` 在查询标签激活时从它读取。
  - **每查询标签一套完整工作区（`QueryWorkspace`，影响不扩散）**：每个查询标签独立持有
    「连接下拉 + 库下拉 + 保存/运行/停止/解释/美化/代码段/询问AI + 编辑器 + 每标签结果区 + 状态行」，
    连接/Catalog/Schema 只影响本标签；左侧树的普通选中、刷新和对象打开不改写已打开查询标签；查询执行/EXPLAIN/保存查询均从**当前工作区**取连接/Catalog/Schema/编辑器/结果区，结果写回对应工作区。
    `_current_profile()` 在查询标签激活时取该工作区的连接；对象浏览页（`domain_stack`）用领域级「树跟手当前连接 + 库」（对象浏览条）。
  - 对象页不再显示全局连接/库浏览条；对象领域上下文由左侧树最近激活元素决定。
    普通“新建查询”只在创建瞬间继承该树上下文，右键“库/模式 → 新建查询”使用右键目标覆盖，创建完成后不再跟随树。
    查询动作按钮与连接/Catalog/Schema 选择器只存在于各自查询工作区。
  - 启动**不**自动选中连接，直到用户在树中激活或在下拉选择；未激活连接时点功能区才提示"请先选择连接"。
  - 左侧树定位到**关闭态连接**时只更新选中项信息，不发出当前连接/对象上下文切换；只有打开态连接才能激活“对象”工作区。

- 对象页没有“默认库”概念：`ConnectionProfile.database` 仅用于 PostgreSQL/GaussDB 协议要求的初始化建连参数，不能作为对象页或其它领域的隐式回退上下文。当前 database/schema 只能来自左树最近激活上下文、标签自身选择或调用方显式参数。
- MySQL/MariaDB 连接编辑表单不展示数据库字段；其数据库列表在连接成功后枚举，用户在对象树或查询工作区中明确选择。PG/GaussDB 的“初始化数据库”字段保持必填，因为驱动协议需要连接目标。
- 当业务路径确实拿不到 database/schema 时，不补选 profile 初始库、第一项库或 `public`；继续走既有 JDBC/SQL 路径，让真实错误通过统一错误处理暴露，避免保护性回退掩盖问题。

## 3.1 SQL 编辑器（monaco-editor）

- **SQL/代码编辑器内核用 monaco-editor（VS Code 内核）**，替代自研 `QPlainTextEdit` 高亮/补全，降低语法提示与高亮成本。
- `MonacoEditorWidget`（`magiccat/ui/monaco_editor.py`）用 QWebEngineView 加载**本地 monaco 资源**
  （`magiccat/resources/monaco/vs`，离线，PyInstaller 随 `resources` 打包）。
- **对外接口与旧 `SqlEditorWidget` 兼容**：`text()`/`all_text()`/`toPlainText()`/`current_sql()`/
  `statements()`/`set_completion_words()`；上层（MainWindow）经这些接口拿文本与补全，逻辑不变。
- 补全词表：Python 传 `set_completion_words` → JS 注册 monaco completion provider（含已连库表/列）。
- **自研 `SqlEditorWidget` 保留**（`magiccat/ui/editor.py`）作回退：`MAGICCAT_EDITOR=plain` 时使用，
  便于无桌面渲染/测试等环境（WebEngine 在 pytest-offscreen 下退出有崩溃隐患）。**真实应用默认 monaco**。
- QtWebEngine 需在 QApplication 前 import（AA_ShareOpenGLContexts）并设
  `QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu"`；`app.py`/`conftest` 已设置。
- 所有“连接选择”下拉框（查询、备份、任务、导入、传输等）条目必须显示对应数据库产品图标，
  统一按 `provider_key` 路由，不能只显示纯文本。
- 对象树中的 schema 与 table 必须使用不同的开源图标，避免层级语义混淆；优先使用 GitHub 可商用素材。
- Monaco 编辑器上下文补全必须覆盖 `FROM`/`JOIN` 后的表/视图（支持部分前缀）、`schema.` 对象前缀、
  以及 `表/别名.` 后的列；补全数据按查询工作区独立刷新。
- Monaco 编辑器选区状态和选中文本必须通过 `onDidChangeCursorSelection` 原生事件经 QWebChannel 一起通知 Python，运行时使用事件快照，禁止用定时器轮询或点击时回退全文。
- 查询标签页的数据库上下文必须独立持有 JDBC `Catalog` 与 `Schema`：MySQL/MariaDB 的 `Schema` 永远为
  `null`，仅设置 `Catalog`；PostgreSQL/GaussDB 两者都设置。切换上下文不得注入或显示 `USE`。
- 查询/结果消息区跟随应用主题，不得固定深色；从隐藏状态首次展开时应保持紧凑的底部比例，不能占满编辑区。
- 查询工作区上下文选择器对齐 Navicat：不显示“连接 / 库 / 模式”文字标签，直接在下拉框中使用连接产品、数据库、模式图标；
  MySQL/MariaDB 没有独立 Schema 时连同模式选择器一起隐藏。
- 查询工作区无选区时，“运行”执行编辑器中的全部 SQL（由服务层逐条切分并返回多个结果集）；有选区时按钮改为“运行已选择的”，只执行选中 SQL。
- 新建查询标签显示名统一为“无标题”；显示名不得承担对象定位职责，查询工作区必须持有独立唯一的内部 `tab_key`。
- 主窗口左侧对象浏览器、中央工作区、右侧信息面板保持三个可独立调宽区域；中央工作区不得以工具栏 `sizeHint` 锁死左右 dock 的分隔条。
- 启动时中央仅显示固定“对象”页，不预建查询标签；查询标签只在新建查询、右键新建查询或打开查询时创建。
- 固定“对象”页的首屏功能域默认为“表”工作区；选中“表”分类或进入表功能域后按其 database/schema 加载表列表。
- 顶部“表/视图/函数/查询”功能域按钮为互斥选择态，由窗口级当前领域 flag 统一驱动中央工作区和按钮高亮。
- 首屏对象工作区没有连接/库上下文时，新增/打开/设计/删除/刷新等操作按钮全部禁用；对象列表成功加载后才恢复可用。
- 表数据页主键读取统一使用 JDBC `DatabaseMetaData.getPrimaryKeys` 和 `KEY_SEQ`，不得手写 `array_position`/`pg_index` 排序 SQL。
- 对象页列表沿用 Navicat 的平面表格风格：主体无边框，表头 section 之间保留浅色分隔线；名称列必须显示对应对象图标（表/视图/查询/函数/触发器/序列）。
- 编辑器标签页按内容类型显示对应图标：固定“对象”页随当前领域切换，查询/表数据/视图/函数/过程/触发器标签分别使用其对象图标；标签标题与内部 `tab_key` 定位键保持独立。

## 3.2 UI 状态管理

- 窗口级跨组件导航状态统一由 `magiccat/ui/state.py` 的 `UiStateStore` 持有，使用不可变 `UiState` 快照、typed action 与纯 `reduce_state`，通过 Qt `state_changed` 信号通知界面。
- `MainWindow` 的当前领域、当前对象连接、对象树 database/schema 上下文、活动标签页和运行中查询计数必须通过 store/reducer 更新；保留的旧属性只能作为兼容访问器，不得绕过 reducer 直接修改状态。
- `UiStateStore.dispatch()` 对等值 action 去重，不重复发出 `state_changed`；状态边界在 reducer 中归一化（活动索引和运行计数不得为负数）。
- `QueryWorkspace` 的连接、Catalog、Schema、编辑器、结果区和状态行属于查询标签私有状态，不纳入窗口级 store，避免左树或其它标签的操作互相覆盖。
- 状态 action 只在 Qt 主线程分发；后台 JDBC 任务通过已有 `run_async` 回调回到主线程后再更新 store。

## 4. 数据访问与方言

- **MySQL：database ≡ schema**（两级即连接→库→分类）；**PostgreSQL：database 与 schema 是两级**（连接→库→schema→分类）。
- **JDBC catalog / schema 语义（重要，用户强调）**：
  - **MySQL JDBC**：只有 **catalog（= database）**，**无 schema**（`getXxx(schema=null, catalog=database, ...)`）。
    元数据查询时把数据库名放 **catalog** 参数；schema 传 `null`。拼限定名时用 `database.table`（反引号）。
    未指定初始 database 时也不得调用 `setCatalog(null)`；数据库枚举直接使用 `getCatalogs()`。
  - **PostgreSQL JDBC**：有标准的 **database（catalog）** 和 **schema** 两个概念；
    `getXxx(catalog=database, schema=schema, ...)` **两者都传**。拼限定名用 `"db"` 只到 `"schema"."table"`（库在连接层，不在表限定名里）。
  - **跨库（PG）**：打开/枚举某库的对象时，需把目标库作为 catalog 传入，并在该库连接上执行（PG 表限定名 `"schema"."table"` 只含 schema，库由连接决定）。
  - 长期查询会话保留 Hikari 连接池以支持并发和 Catalog/Schema 隔离；连接测试、跨库一次性元数据等短操作直接建立 JDBC 连接，不创建短命连接池。
- **连接、database、schema、table、view、column 的基础元数据统一优先用 JDBC 标准 API**（`DatabaseMetaData`）；
  MySQL 只有 JDBC 不覆盖的引擎/估计行数/索引/触发器等富信息才走 `information_schema`，且不得让这些 SQL 路由到 PG/GaussDB。
  若 PG/GaussDB 驱动的 `getCatalogs()` 只返回当前库，数据库全量枚举允许定向使用 `pg_database` 兜底。
- 标识符/分页语法**按方言**：PG 双引号 + `LIMIT n OFFSET m`，MySQL 反引号 + `LIMIT offset, limit`。
- 应用层方言由 `magiccat/services/dialects.py` 的 `Dialect` 能力对象统一提供：是否支持独立 schema、是否支持序列、分页片段、database 是否等价 schema、初始化数据库是否必填；UI 领域判断必须使用这些能力，不能散落硬编码产品名。
- 对象页的作用域语义：MySQL/MariaDB 在应用对象树中把 database 视作 schema；PostgreSQL/GaussDB 必须同时激活 database 与 schema 才加载表/视图/函数等 schema 作用域对象，也不得激活表工作区。仅选中 database 时清空旧列表并保持未加载，不擅自补 `public`、初始库或首个 schema；缺少作用域的底层调用不由 UI 伪造默认值。
- 表数据浏览固定每页 1000 行；分页器始终允许向后翻页，超出结果集时自然显示空页；在同一当前筛选结果集上返回窗口总数。禁止单独执行全表 `SELECT COUNT(*)`；底部状态栏左侧显示本次分页 SQL，右侧显示当前页/当前结果集总条数与分页器。
- 表数据页底部状态栏按 Navicat 分为独立区段：SQL、记录状态、分页器之间使用竖向分隔线；有数据时显示“第 n 条记录（共 m 条）于第 p 页”，空页只显示“第 p 页没有记录”。
- 新建连接向导第二页标题必须跟随当前产品显示（如 MySQL 连接、PostgreSQL 连接、GaussDB 连接），不得固定为 MySQL。
- **限定名 = 每个标识符分别加引号，再以 `.` 连接**：`"schema"."table"`（PG）、`` `schema`.`table` ``（MySQL）。
  **绝不能把整个 `schema.table` 当成一个标识符包进一对引号**（即 `"schema.table"` 或 `` `schema.table` ``），
  否则 PG/MySQL 都报 "relation does not exist / 找不到"。
- **避免 N+1**：循环内不做数据库 I/O；同类信息尽量**一次批查**（用户明确定义 N+1 = 循环内网络 IO）。
- 跨库枚举（如 PG 某库的 schema/对象）需**临时连到目标库**查询。
- 连接配置有 `provider_key`（方言/驱动 key），贯穿 open/test/连接图标/元数据。
- GaussDB 与 PostgreSQL 同源，使用 `jdbc:gaussdb://`、双引号和 PG 兼容对象树；
  JDBC 驱动 `gaussdbjdbc.jar` 受版权约束，不随软件分发。用户通过「工具 → 环境」指定本机 JAR，
  设置保存于 SQLite，连接打开时动态加载。
- GaussDB 表对象页列表必须走目标 Catalog+Schema 的标准路径，不能复用包含反引号和
  `ENGINE`/`TABLE_ROWS` 等 MySQL 专用字段的批量查询。
- GaussDB 序列列表必须使用一条批量 SQL 一次返回名称、所有者、当前值、步长、最小/最大值、开始值、缓存和循环标志；
  不再先用 JDBC `DatabaseMetaData.getTables(..., {"SEQUENCE"})` 枚举名称再补查，避免两阶段读取和 N+1 演进风险。
- 序列“设计”点击确定后必须执行 ALTER SQL 并沿用序列页的 database/schema 上下文；当前值使用 `RESTART WITH`，开始值使用 `START WITH`，成功后弹出反馈并刷新列表。
- PostgreSQL / GaussDB 的连接配置中“初始化数据库”为必填项，默认值统一为 `postgres`；
  该值只决定首次连接目标，数据库树仍必须枚举服务器上的其它数据库。
- GaussDB 与 PostgreSQL 同源，使用 `jdbc:gaussdb://`、双引号和 PG 兼容对象树；
  JDBC 驱动 `gaussdbjdbc.jar` 受版权约束，不随软件分发。用户通过「工具 → 环境」指定本机 JAR，
  设置保存于 SQLite，连接打开时动态加载。
- PostgreSQL / GaussDB 的连接配置中“初始化数据库”为必填项，默认值统一为 `postgres`；
  该值只决定首次连接目标，数据库树仍必须枚举服务器上的其它数据库。

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
- 遇到明确的 `PermissionError` / “拒绝访问”时，先核对目标路径和操作范围，再优先申请该目标所需权限；不得将权限环境问题误判为功能失败。
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
- **MagicCat 已按此重构本地存储**（三合一，对标 Navicat；不兼容旧 profiles.json/query.json/history.json，
  旧数据弃用、不迁移、不留兼容代码）：
  - 连接配置 → **用户数据目录下的版本化 JSON** `connections.json`（密码明文，原子写入；不依赖注册表）。
  - 查询 SQL 内容 → **.sql 文件** `<MAGICCAT_HOME>/queries/<profile_id>/<schema>/<name>.sql`。
  - 元数据缓存/历史/收藏/设置/片段/任务/窗口状态 → **SQLite** `metacache.db`（kv / metadata_cache / history / favorites 表）。
  - 统一入口：`magiccat/storage/{__init__,profile_store,sqlite_store,query_store}.py`，根目录 `storage.home_dir()`；未设置 `MAGICCAT_HOME` 时按 Windows `%APPDATA%`、macOS `~/Library/Application Support`、Linux `$XDG_CONFIG_HOME` 选择目录。
  - 相关服务（ProfileStore/QueryLibrary/HistoryStore/AppSettings/SnippetStore/TaskStore）接口保持，
    内部实现改为上述新存储。
