# MagicCat 设计方案（对标 Navicat 的数据库管理工具）

- 版本：v0.1（初稿）
- 状态：待评审
- 技术栈主约束：**Python + PySide6（界面）＋ Java JDBC（数据访问）**
- 已确认决策：桥接方式 = JPype 进程内嵌 JVM；首发数据库 = MySQL / MariaDB；首发平台 = Windows + 安装包

---

## 1. 项目定位与功能范围

### 1.1 定位

MagicCat 是一款**跨数据库的桌面级数据库管理与开发工具**，对标 Navicat Premium 的核心工作流：连接管理 → 对象浏览 → SQL 开发 → 数据查看/编辑 → 导入导出 → 结构设计，力争在常用场景做到"轻量、稳定、顺手"，而不是像素级复刻 Navicat。

### 1.2 功能矩阵（对标项 → MagicCat 处理方式）

| Navicat 能力 | MagicCat 处理 | 阶段 |
|---|---|---|
| 连接管理（多库、分组、密码保存、测试连接） | 支持（分组树 + 跨平台 JSON 存储） | M2 |
| 对象浏览器（库/表/视图/函数/存储过程/触发器/用户…） | 支持，MySQL 全对象类型 | M2 |
| SQL 编辑器（高亮/自动补全/多标签/美化/参数/历史） | 支持（自研编辑器组件） | M3 |
| 结果网格（编辑/筛选/排序/分页/大结果集） | 支持（虚拟滚动 + 服务端分页） | M3~M4 |
| 表设计器（可视化列/索引/外键/约束，生成 DDL） | 支持（生成 CREATE/ALTER + 变更预览） | M4 |
| 数据导入/导出（CSV/Excel/JSON/SQL） | 支持（向导 + 后台任务） | M5 |
| 数据传输 / 结构同步 | 数据传输支持，结构同步放 M6 | M6 |
| ER 图 | 支持（QGraphicsScene 自绘） | M6 |
| 备份/恢复、计划任务 | MySQL 转储/恢复向导 | M6 |
| 查询历史、收藏、片段、图表 | 历史/收藏支持，图表延后 | M3+/远期 |

### 1.3 MVP 边界（明确不做，避免范围失控）

- 暂不支持 NoSQL / Redis / 云数据库专有面板
- 暂不做多人协作、云同步
- 暂不做"图表仪表盘"类数据分析大屏
- 编辑类功能默认走**主键定位更新**，不保证对"无主键/无唯一键表"的编辑安全（给出降级提示）

---

## 2. 技术选型总览

| 层次 | 选型 | 理由 / 备注 |
|---|---|---|
| GUI | PySide6（Qt6），Python 3.12 | 用户指定；跨平台、控件成熟 |
| 桥接 | **JPype1 进程内嵌 JVM** | 用户已确认；单进程、调用直接、免网络协议层 |
| JVM | Java 17（Temurin），发布时用 jlink 定制运行时 | 已装 Java 17；jlink 可裁剪体积 |
| JDBC 驱动 | mysql-connector-j 8.4+（或 mariadb-java-client 备选） | MySQL/MariaDB 双兼容 |
| 连接池 | HikariCP | 成熟稳定、可监控 |
| Java 工程 | Maven 3.6+，Java 17 | 已装 |
| 编辑器 | 自研：QPlainTextEdit + QSyntaxHighlighter + QCompleter | PySide6 官方不带 QScintilla；不引入 QWebEngine 重壳 |
| 结果网格 | QTableView + 自定义 QAbstractTableModel/Delegate | 虚拟行、类型化渲染、行内编辑 |
| SQL 处理 | sqlparse（切分/美化）；jsqlparser（JVM 内，结构 diff、语句分类） | 分阶段引入 |
| Excel/CSV | openpyxl / csv / pandas(可选) | Python 侧流式处理 |
| 数据交换 | 无网络协议，直接对象传递（JPype） | 定义 Python↔Java 的"数据类契约"（见 §6） |
| 测试 | pytest + pytest-qt（Python）；JUnit 5（Java） | 桥接层单测打桩 |
| 打包 | PyInstaller + jlink JRE + Inno Setup | 见 §11 |
| 代码规范 | Python: ruff + black；Java: spotless/Checkstyle 可选 | |

---

## 3. 总体架构

### 3.1 架构图

```
┌────────────────────────────────── MagicCat 单进程 ──────────────────────────────────┐
│                                                                                      │
│  ┌──────────────────────── PySide6 界面层（Python 线程） ────────────────────────┐   │
│  │  MainWindow(Dock 布局)                                                        │   │
│  │   ├ ConnectionTree │ SqlEditor │ DataGrid │ TableDesigner │ Import/Export…    │   │
│  │   └────────────── 业务外观层 services（Python） ───────────────────────────── │   │
│  │      ConnectionService · MetadataService · QueryService · EditService         │   │
│  │      DdlService · TransferService —— 全部为“纯 Python 门面 + 线程封装”         │   │
│  └───────────────┬────────────────────────────────────────────────────────────────┘   │
│                  │ JPype（自动线程 attach；Java 调用期间释放 GIL）                    │
│  ┌───────────────▼──────────────── JVM 内 JDBC 数据访问层（Java） ────────────────┐   │
│  │  BridgeFacade（Java 侧唯一入口，按“会话”提供服务）                             │   │
│  │   ├ ConnectionRegistry（HikariCP 连接池，按连接配置 ID 管理）                  │   │
│  │   ├ MetadataEngine（DatabaseMetaData + information_schema 缓存）               │   │
│  │   ├ QueryExecutor（执行/流式分页/取消/统计信息）                               │   │
│  │   ├ StatementBuilder（主键定位 UPDATE/DELETE、LIMIT 方言生成）                 │   │
│  │   └ Dialect SPI（当前实现 MySQLDialect；为 PG/Oracle 预留接口）                │   │
│  └──────────────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 进程模型

- **单进程双运行时**：一个 OS 进程内同时有 Python 解释器和 JVM。
- JVM **必须在应用启动早期、任何 Java 类被引用前一次性启动**（JPype 硬性约束）；之后不可重启。
- 启动顺序：`main()` → 解析配置/classpath（驱动 jar、自研 bridge jar、jlink 运行时路径）→ `jpype.startJVM(...)` → 初始化 `BridgeFacade` → 打开主窗口。

### 3.3 线程模型（JPype 方案的核心设计点）

| 关注点 | 设计 |
|---|---|
| UI 响应 | 所有 JDBC 调用禁止在 GUI 主线程执行；统一封装为 `QThreadPool`/`QRunnable` 后台任务 + signal/slot 回传 |
| JPype 线程 | JPype 会把首次调用 Java 的 Python 线程自动 attach 到 JVM；后台线程池按需 attach，**退出前统一 detach** |
| GIL 行为 | Python→Java 调用期间 JPype 会释放 GIL（阻塞式 JDBC 调用不冻结其他 Python 线程）；Java→Python 回调会重新拿 GIL，回调体必须短小 |
| 查询取消 | 每个查询任务持 `JStatement` 句柄；点"取消"时在另一线程调 `stmt.cancel()`（MySQL 走 `KILL QUERY` 语义），配合心跳 |
| 连接归属 | 同一"连接配置"的会话（Session）串行使用一个池内连接执行语句，避免多线程抢用同一 Statement；数据网格编辑与查询分开 |

> 说明：用户选定 JPype 而非独立 Java 桥接进程。为此在架构上做三处对冲：
> 1) **Java 侧薄门面**：所有 JDBC 逻辑收敛在 `BridgeFacade` 一组类里，未来若 JPype 在大结果集/稳定性上不达标，可平移改造为 WebSocket 服务进程而不动界面层；
> 2) **启动即校验**：JVM 启动失败/驱动加载失败给出明确引导（自动探测 java.home 或内嵌 JRE）；
> 3) **看门狗式健康检查**：后台线程周期性 ping JVM；异常时提示"数据访问引擎不可用"，引导重启应用（单进程方案无法热重启 JVM）。

---

## 4. 数据访问层设计（Java 侧）

代码位于 `java-bridge/`（Maven 工程），产出 `magiccat-bridge.jar` 放入 Python 包资源目录。

### 4.1 模块划分

| 模块 | 职责 | 关键类 |
|---|---|---|
| facade | 唯一门面，暴露一组粗粒度方法（减少 Python↔Java 往返） | `BridgeFacade` |
| session | 一个"连接配置 + 打开状态"的运行上下文 | `JdbcSession` |
| pool | HikariCP 管理：按 `configId` 建立/复用/回收 | `ConnectionRegistry` |
| metadata | 元数据拉取与缓存：库→表/视图/过程/函数/触发器/用户→列/索引/外键 | `MetadataEngine`, `MySqlMetadataProvider` |
| query | 执行、分页取数、取消、行数估算、结果元数据 | `QueryExecutor`, `ResultPage` |
| edit | 主键定位 UPDATE/DELETE/INSERT、批量提交 | `RowMutator` |
| ddl | 方言化 DDL 生成（MySQL Dialect）；diff 由 jsqlparser 支撑 | `DdlGenerator`, `MySqlDialect` |
| convert | JDBC → 跨语言数据类转换 | `JdbcValueConverter` |
| util | 日志（slf4j）、异常归一化（转成 MagicCat 错误码 + 消息，不带 Java 堆栈噪音） | `McException` |

### 4.2 元数据模型（统一对象树）

```
Server
└─ Database ─ Table / View / Routine(Procedure|Function) / Trigger / User / Event
             └─ Column(name,type,nullable,default,charset,comment,key,extra…)
             └─ Index(columns,unique,method…)
             └─ ForeignKey(name,cols,refTable,refCols,onUpdate,onDelete)
```

实现策略：优先走 `DatabaseMetaData`，对 MySQL 专有信息（字符集、注释、引擎、分区）用 `information_schema` 补充查询；结果**进程内缓存 + 失效刷新**（用户右键"刷新"清缓存）。

### 4.3 查询执行与分页

- 查询返回 `ResultPage{ columns, rows(可空值标记), total, truncated, sql }`。
- 表数据页固定每页 1000 行，采用服务端分页；MySQL/MariaDB 使用 `LIMIT offset,size`，PostgreSQL/GaussDB 使用 `LIMIT size OFFSET offset`。分页器始终允许向后翻页，超出结果集时自然返回空页，不再单独执行全表 `SELECT COUNT(*)`。
- `total` 由窗口统计返回当前筛选结果集的总条数，不是忽略筛选条件的全表计数；底部状态栏分为 SQL、记录状态、分页器三个区段并用竖线分隔，有数据时显示“第 n 条记录（共 m 条）于第 p 页”，空页只显示“第 p 页没有记录”。
- 单元格统一用 `JdbcValueConverter` 转成稳定 Java 数据类型（见 §6），避免 `ResultSet.getObject()` 的方言抖动。

### 4.4 取消机制

- 查询任务在 Java 侧持有 `Statement`，Python 侧"取消"请求调 `cancel(statementId)` → `stmt.cancel()`；MySQL Connector/J 对 `cancel` 的实际效果是中断读取，必要时 Java 侧补充 `KILL QUERY <threadId>`。

### 4.5 连接池与保活

- HikariCP 参数：`maximumPoolSize=8`、`idleTimeout=10min`、`maxLifetime=30min`、`connectionTimeout=10s`，按连接配置维度独立池。
- 空闲保活：`connectionTestQuery = SELECT 1` + 前端可见的"连接状态"指示灯。
- 测试连接 = 独立短连接，不占用业务池。

---

## 5. 界面层设计（PySide6）

### 5.1 主窗口布局

- 左侧：连接导航树（可折叠、分组、搜索过滤）
- 中央：QSplitter 上下分区——上：SQL 编辑器多标签；下：结果集/消息/历史 多标签
- 右侧（可隐藏）：对象详情面板、表数据预览
- 底部：任务进度面板 + 输出日志
- 全局菜单/工具栏：连接、查询、工具（导入导出/数据传输/备份）、窗口布局、设置（i18n/主题）

### 5.2 模块清单与关键类

| 模块 | 关键实现 | 说明 |
|---|---|---|
| ConnectionManager | `ConnectionService` + `JsonProfileStore`（用户文档目录下的 `MagicCat/<display>/Servers/<连接名称>/connection.json` 按产品 display 逐连接目录保存 JSON + 独立 `Premium/profiles/vgroup.json`，明文口令） | 分组树、拖拽调整归属、复制连接、测试连接 |
| ObjectExplorer | `ObjectTreeModel` + 右键菜单 | 按 4.2 对象树展示；双击表 → 表设计/数据页 |
| SqlEditor | `SqlEditorWidget`（自研） | 多标签；语法高亮（QSyntaxHighlighter，MySQL 关键字/字符串/注释/变量）；**自动补全**：关键字 + 已连库的表/列（元数据缓存驱动 QCompleter）；语句级执行/选中执行/全部执行；sqlparse 美化；查询历史落盘 |
| ResultGrid | `ResultTableModel` + `ResultTableView` | 虚拟滚动（单次最多取页大小，滚动到底自动取下一页）；类型化渲染与编辑；右键：复制行/复制带表头/导出当前结果/筛选排序追加 SQL |
| TableDesigner | `TableDesignDialog` | 网格化编辑列/索引/外键/约束；实时生成 CREATE/ALTER 预览；结构 diff 高亮 |
| ImportExport | `TransferWizard` | CSV/Excel/JSON/SQL 双向向导；后台线程 + 进度条 + 可取消 |
| ToolWindow | `TaskCenter` / `LogPane` | 任务状态（运行中/成功/失败/耗时）与日志 |
| Settings | `SettingsDialog` | i18n（zh-CN/en）、主题（亮/暗，QSS）、编辑器主题/字号、快捷键 |

### 5.3 异步封装（Python 侧门面模式）

```python
# 伪代码：所有 services 统一走该封装
def run_jdbc(label: str, cancel_token, fn: Callable[[], JavaObject]) -> Job:
    job = Job(label=label, cancel_token=cancel_token)
    worker = JdbcWorker(fn, cancel_token)   # QRunnable：内部 attach JVM 并执行
    worker.signals.result.connect(job.done)  # 自动回主线程
    QThreadPool.globalInstance().start(worker)
    return job
```

- 每个连接配置在 Python 侧持有 `SessionHandle`；网格翻页、编辑提交、补全元数据均走后台任务。
- 所有 Java 对象**不得直接泄漏进 UI 线程状态**；服务层返回 Python 原生值（str/int/bytes/datetime…）。

---

## 6. 类型系统与数据契约

JPype 下不需要序列化，但仍需**稳定的跨语言类型映射**（避免方言间漂移），映射表：

| JDBC（Java 侧转换后） | Python | UI 渲染 |
|---|---|---|
| `NULL` | `None` + "是否为空"标记 | 灰底 NULL 徽标 |
| `Boolean` | `bool` | 复选框/对勾 |
| `Integer/BigInt/TinyInt…` | `int` | 右对齐，千分位可选 |
| `Decimal` | `Decimal`（保持精度，绝不 float） | 货币/小数对齐 |
| `Float/Double` | `float` | 默认 |
| `Date/Time/Timestamp` | `datetime.date/time/datetime` | 按连接时区格式化 |
| `String/Text 系列` | `str` | 左对齐；超长省略 + 悬浮全文 |
| `byte[]`（BLOB/BINARY） | `bytes` | 十六进制/图片缩略预览；**懒加载**（列表页默认取前 N 字节，双击拉全文） |
| JSON 类型 | `str`（原始 JSON）+ 美化视图 | 语法着色悬浮窗 |
| 其它（geometry/枚举/位…） | 规范化为字符串 + 类型名 | 展示原始文本 |

- 元数据携带列名、Java 类型名、精度/标度，供渲染器选型。
- BLOB 默认策略：结果分页查询只取 `SUBSTRING(blob, 1, 4096)` 预览，双击单元格单独拉取完整内容，避免大字段撑爆内存。

---

## 7. 安全设计

| 项 | 方案 |
|---|---|
| 连接口令存储 | 用户文档目录下的 `MagicCat/<display>/Servers/<连接名称>/connection.json`（按产品 display 逐连接目录保存版本化 JSON，`password` 明文；同一大写 `provider_key` 内连接名称唯一，不同产品可同名，不生成哈希或碰撞后缀）；组关系独立保存于 `MagicCat/Premium/profiles/vgroup.json`，结构对齐 Navicat 的 `version` / `vgroups` / `connections`；文件采用原子替换，Unix 权限为 `0600`，不使用 Windows 注册表 |
| 内存中的口令 | 连接建立后即从内存配置中清除明文引用；日志一律脱敏（`****`） |
| 传输 | 直连 JDBC，无自建网络层；无中间人面 |
| SQL 安全 | 编辑类 SQL 只允许主键定位的 UPDATE/DELETE 由程序生成；用户自定义 SQL 属用户行为，提供"事务提交前确认"开关 |
| 崩溃数据 | 未提交编辑在关窗前强提示；历史/片段为本地明文文本（用户自担） |

---

## 8. 关键流程（时序摘要）

1. **打开连接**：UI 填配置 → 后台 `testOrConnect(configId)`（Java 侧建 Hikari 池并 `SELECT 1`）→ 成功后左侧树展开库列表（元数据懒加载，点开一层拉一层）。
2. **写 SQL 并执行**：编辑器光标/选中段 → 语法块切分 → 后台执行 → 结果页回传 → 网格首屏渲染 + 状态栏"行数/耗时"；可随时取消。
3. **编辑单元格保存**：网格改一格 → 单元格进入"待提交"状态（黄底）→ 点保存 → Java 侧按主键生成 UPDATE 并执行 → 刷新受影响行。
4. **导入导出**：向导定参数 → 后台任务流式读写 + 进度回调 → 完成写日志。

---

## 9. 工程结构

```
MagicCat/
├─ magiccat/                      # Python 主包
│  ├─ __main__.py / app.py        # 入口：JVM 启动 → 主窗口
│  ├─ core/                       # 启动编排、配置、异常、i18n
│  ├─ jvm/                        # 运行时资源：magiccat-bridge.jar + 驱动 jar
│  ├─ bridge/                     # JPype 封装层（加载/门面代理/Java 类包装）
│  ├─ services/                   # Python 门面（connection/metadata/query/edit/ddl/transfer）
│  ├─ models/                     # dataclass 数据模型（元数据/连接配置/结果页）
│  ├─ ui/
│  │  ├─ mainwindow/  widgets/(editor,grid,tree,designer,wizard,panels)
│  │  └─ resources/  (qss/icon/translations)
│  └─ utils/
├─ java-bridge/                   # Maven 工程（输出 jar 至 magiccat/jvm/）
│  ├─ pom.xml
│  └─ src/main/java/com/magiccat/bridge/…
├─ tests/                         # pytest(+pytest-qt)；jvm 侧 JUnit 在 java-bridge 内
├─ packaging/                     # magiccat.spec、jlink 脚本、Inno Setup 脚本、图标
├─ scripts/                       # build_java.bat / dev_run.bat
├─ docs/
└─ README.md
```

---

## 10. 里程碑与任务分解

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **M0 方案** | 本文档评审通过 | 关键决策确定、范围锁定 |
| **M1 技术验证(POC)** | 跑通"PySide6 → JPype → HikariCP → mysql-connector-j → MySQL"全链路：启动 JVM、连接、执行 `SELECT`、翻页、取消、类型映射、打包冒烟 | 能在真实 MySQL 上完成查询并把 10 万行分页取回 UI；JVM 启动与关闭干净 |
| **M2 连接与对象浏览** | 连接管理（增删改/测试/加密存储/分组）、对象树全类型浏览与刷新、右键基本操作（打开表/新建库） | 常用连接配置可一键打开，对象树浏览不卡 UI |
| **M3 SQL 开发闭环** | 编辑器（高亮/补全/多标签/历史/美化）、执行与多结果集、消息面板 | 日常 SQL 开发流程可用 |
| **M4 数据与结构编辑** | 结果网格（分页/排序筛选/编辑保存/复制导出）、表设计器（CREATE/ALTER 预览）、外键联动 | 建表-改表-导数据小闭环自测通过 |
| **M5 数据传输** | 导入/导出向导（CSV/Excel/JSON/SQL）、库间数据传输（MySQL→MySQL） | 万行级文件导入导出稳定、可取消 |
| **M6 进阶特性** | ER 图、备份/恢复、计划任务、设置/i18n/主题完善 | 功能面基本对标 Navicat 常用项 |
| **M7 发布** | 内嵌 jlink JRE 的 PyInstaller 打包 + Inno Setup 安装包；安装/升级/卸载自测；性能与稳定性打磨 | Windows 全新机器一键安装可用 |

> 每阶段独立可交付；M1 是"技术否决点"——若 JPype 链路在 M1 暴露不可控问题（如大结果集卡顿、打包后 JVM 启动失败），则触发备选：改造为 §3.3 预留的独立 Java 桥接进程（界面层不动，仅替换 bridge 层实现）。

---

## 11. 打包与发布（Windows）

1. Java 侧：Maven `package` 产出 `magiccat-bridge.jar` + 复制 `mysql-connector-j*.jar` → `magiccat/jvm/`。
2. JVM 运行时：用 `jlink --add-modules java.sql,java.naming,java.management,jdk.unsupported …` 裁剪出 `runtime/jre`（目标体积 ~40–60MB）。
3. Python 侧：PyInstaller（`--windowed`，收集 JPype 原生库与上述 jvm 资源），已知坑位统一处理：JPype 动态库 hidden import、`java.home` 探测、资源路径在 `sys._MEIPASS` 下解包。
4. 安装器：Inno Setup —— 装到 `%LocalAppData%\Programs\MagicCat`，写开始菜单/桌面快捷方式，卸载不删除用户文档目录下的 `MagicCat` 数据。
5. 体积预估：Python+Qt ≈ 150–250MB + JRE ≈ 60MB + 驱动 ≈ 5MB；如需瘦身可对 Qt 模块裁剪。

---

## 12. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| JPype 与 PyInstaller/多线程兼容坑 | 高 | M1 先行验证；预留 sidecar 改造点（§3.3）；所有 Java 调用收敛在 bridge 层 |
| JVM 崩溃/泄漏导致整应用退出 | 高 | 资源统一释放（池/Statement/ResultSet try-with-resources）；健康检查提示重启 |
| 功能面过大拖慢交付 | 中 | MVP 边界锁定（§1.3），按里程碑验收 |
| 大结果集内存与 UI 卡顿 | 中 | 服务端分页 + 虚拟滚动 + BLOB 懒加载（§4.3/§6） |
| MySQL 方言细节（含 8.0 与 MariaDB 差异） | 中 | Dialect SPI + information_schema 双路径 + 双版本回归测试 |
| 中文/编码、时区处理错误 | 中 | 统一 UTF-8；连接参数显式 `useUnicode&characterEncoding`；时间统一走连接时区 |
| jlink/PyInstaller 打包体积与兼容 | 低 | §11 裁剪与冒烟测试 |
| 主密码遗忘 | 低 | 首次设置即提示"无法找回"，提供重置（清空口令库重录） |

---

## 13. 开发规范

- Python：类型注解全覆盖；ruff 检查 + black 格式；service 层只做门面、不含 JDBC 细节。
- Java：包名 `com.magiccat.bridge`；slf4j 日志；所有对外方法抛 `McException`（错误码 + 用户可读消息）。
- 错误码：`MC-xxxx` 全局编号，Python 侧统一转成对话框/状态栏提示，不外泄 Java 堆栈。
- Git 分支：`main`（可发布）+ `dev`；里程碑合入打 tag `M1..M7`。
- 环境依赖（本机已具备）：Python 3.12.12、Java 17（Temurin）、Maven 3.6.3；数据库联调用 MySQL 8.x（容器或本机均可）。

---

## 附录 B：实施状态（持续更新）

| 里程碑 | 内容 | 状态 | 关键验证 |
|---|---|---|---|
| M0 | 方案评审 | ✅ | 本文档 |
| M1 | JPype→HikariCP→MySQL 全链路 POC | ✅ | `scripts/poc_m1.py` 一次通过（MySQL 8.4.7） |
| M2 | 连接管理（密码存储）+ 对象浏览 | ✅ | pytest：配置回环 / 元数据 / Qt 对象树异步加载（历史记录） |
| M3 | SQL 编辑器（高亮/补全/多标签/历史/美化）+ 多结果集 | ✅ | 真实建表-插入-查询-错误不中断 |
| M4 | 数据页（分页/主键编辑/增删行/筛选/排序）+ 表设计器（ALTER 预览/应用） | ✅ | CRUD / 无主键只读 / DDL 片段生成 |
| M5 | 导入导出 CSV/Excel/JSON/SQL | ✅ | 四格式回读 + CSV 导入 + SQL 回灌 |
| M6 | 主题、ER 图、SQL 备份/恢复、收藏/复制 | ✅ | ER PNG 导出；备份→删表→恢复→FK 仍生效 |
| M7 | Windows 打包：PyInstaller + jlink 内嵌 JRE + 图标 | ✅ | `MagicCat.exe --selftest` 在无系统 Java 下 `jre_bundled:true` |
| M8 | 打磨：收藏/复制/关于/图标/README | ✅ | 25 项自动化测试全绿 |
| M9 | DELIMITER 支持（存储过程/函数多语句脚本执行） | ✅ | 建过程→CALL→DROP 端到端 |
| M10 | 数据传输（库间/表间复制：结构+数据、进度/取消） | ✅ | 结构复制+数据追加双路径验证 |
| M12 | 对象管理：新建库/新建表/清空表/删除表（设计器新建模式） | ✅ | 新建表流端到端 |
| M13 | 结果导出 CSV/导出跟随筛选/窗口标题联动 | ✅ | 网格回读+筛选行数验证 |
| M14 | 多标签并行执行 + 表右键复制 CREATE | ✅ | 并行双查询均完成 |
| M15 | 运行中查询取消（Statement.cancel，KILL 语义） | ✅ | SLEEP(30) 取消后 <10s 返回 |
| M16 | 超长单元格截断(tooltip 全文)/复制导出保留全文 + 文件日志 | ✅ | 截断与全文双路径断言 |
| M18 | 对象树名称过滤 + 窗口几何记忆 | ✅ | 过滤/恢复 + 几何落盘断言 |
| M19 | 全库备份恢复含 视图/例程/触发器（单连接 setCatalog 恢复） | ✅ | 建表+视图+过程+触发器 备份→重建库→恢复→逐项验证 |
| M20 | 计划任务（运行期间定时自动备份；防重入/状态记录） | ✅ | 到期逻辑/锁/真实备份文件 |
| M21 | Java 错误文案去重 + 快捷键帮助 + 打开日志目录 | ✅ | 前缀剥除/格式化单测 |
| M22 | 视图/例程/触发器 右键（复制 CREATE/删除对象） | ✅ | DDL 取回+DROP 通路面 |
| M23 | 便携版发行包（build_release.ps1 → zip，含内嵌 JRE/图标，关键文件校验） | ✅ | zip 68MB 校验 OK + exe 自检 |
| M24 | 元数据实现按产品自动选择：标准 JDBC(DatabaseMetaData) vs MySQL information_schema | ✅ | 作用域回归（mysql.user 命中、不混他库） |
| M25 | 方言注册表与 URL/标识符构造（MySQL/MariaDB 支持，PG/Oracle/SQLServer 登记待接入） | ✅ | URL/引号单测；发行包重建通过 |
| M26 | 服务器/连接信息面板（标准 JDBC DatabaseMetaData：产品/版本/驱动/URL/用户） | ✅ | 服务取证 + 面板回填断言 |
| M27 | MySQL 完备：EXPLAIN 执行计划 + 数据页默认主键序 | ✅ | 计划行/稳定翻页断言 |
| M28 | DDL 生成保真：列字符集/排序规则/ON UPDATE/关键字默认值(CURRENT_TIMESTAMP 免引号) | ✅ | 语法顺序修正 + 保真单测 |
| M29 | 表设计器索引增删（普通/UNIQUE；列随删时跳过冗余 DROP） | ✅ | 加/删索引端到端 + 不重建未变索引 |
| M30 | 表设计器外键增删（单列；ON DELETE/UPDATE 规则） | ✅ | CASCADE 加/删端到端 + 规则断言 |
| M31 | 数据页批量粘贴 TSV（Excel 复制到单元格区域，标记待保存） | ✅ | 两行两列 dirty 断言 |
| M32 | 具名查询库（对标 Navicat “查询”：树节点/另存/打开/删除，绑定连接+库） | ✅ | 存取覆盖/树节点/编辑器打开 |
| M33 | 数据库转储 SQL 文件（库右键：结构和数据 / 仅结构，后台+取消） | ✅ | 两模式 INSERT 断言 |
| M34 | Bugfix：连接信息面板启动黑块（QScrollArea 视口自填充 + 深色 QSS 覆盖） | ✅ | autofill 标志回归 |
| M35 | 转储 SQL 保持 schema 级；标准层 catalog/schema 映射收敛（MySQL=catalog 走信息层，PG 走 catalog=null+schema） | ✅ | 71 回归全绿 |
| M36 | 运行 SQL 文件…（库节点；以该库为默认目标，未加前缀语句落地正确） | ✅ | 任意 SQL + 目标库断言 |
| M37 | 对象树按 Navicat 统一为「函数」分类（过程+函数同组；不再叫“例程”/“存储过程”） | ✅ | 单分类计数 + 无旧文案 |
| M38 | 「新建函数…」函数向导（过程/函数+名称）→ 编辑器模板（含 DELIMITER） | ✅ | 模板生成 + 真创建函数/过程 |
| M39 | 双击“函数”节点打开其 CREATE 定义到编辑器 | ✅ | 打开回填 + 标签 + 连接绑定 |
| M40 | 自有矢量对象图标（函数 fx 蓝 / 存储过程 P 绿 / 表/视图/触发器/库/连接/查询） | ✅ | 全类型非空 + 过程/函数相异 |
| M41 | 库右键「编辑数据库…」：查看/修改字符集与排序规则（ALTER DATABASE） | ✅ | 下拉联动 + ALTER 生效断言 |
| M42 | 库展开为 Navicat 式固定分类（表/视图/函数/触发器/查询/备份，空也常驻） | ✅ | 复现脚本 + 回归 |
| M43 | 顶部快速访问栏（连接/新建查询/表/视图/函数，带图标） | ✅ | 动作存在 + 图标非空 |
| M44 | 菜单动作图标化（连接/新建查询/执行/取消/保存查询；Qt/Navicat 对齐） | ✅ | 新图标类型覆盖 |
| M45 | 修正：图标按钮归入菜单栏下方独立工具栏（图标+文字在下），菜单项去图标 | ✅ | 工具栏样式/动作断言 |
| M46 | 快速栏对齐 Navicat 全套：连接/新建查询/表/视图/函数/用户/其它/查询/备份/自动运行/模型/BI | ✅ | 全按钮+图标断言 |
| M47 | 用户管理面板（列表/新建/编辑密码/删除/权限查看；对标 Navicat 用户） | ✅ | 服务 CRUD + 面板加载断言 |
| M48 | 快速栏只放已实现功能；移除未实现的 其它/BI（避免误判） | ✅ | 无占位断言 |
| M49 | 编辑/新建用户表单升级：用户名/主机/插件/密码/确认/密码过期策略 + SQL 预览 | ✅ | 插件/过期策略断言 |
| M50 | 逐层懒加载：库→分类骨架→展开分类才取对象；ER 改全库批查（消除 N+1） | ✅ | 分类懒加载 + ER 批查回归 |
| M51 | 补全词表一次批查全库表名（去掉每库一查）；发行包含 M36–M50 | ✅ | 82 回归 + exe 自检 |
| M52 | 探针测试证实“点击展开才取该层”：库→骨架无查询、分类展开各仅一次 | ✅ | 查询计数断言 |
| M53 | 消除循环内 DB IO：备份/转储 全库列/索引/外键各批查一次（逐表元数据移出循环） | ✅ | M19/M33/M6 备份回归 |
| M54 | 数据页保存单连接批量执行（多行 UPDATE/INSERT 一次 Java 调用，去掉逐行往返） | ✅ | 两行编辑落库断言 |
| M55 | Bugfix：移除连接级多余“查询”节点（Navicat 仅库级；保存/删除刷新到库级分类） | ✅ | 库级查询分类断言 |
| M56 | 收拢查询操作：删除旧“查询/连接”散置工具栏，新增「查询工具」栏（连接/库 + 保存/美化/运行/停止/解释） | ✅ | 构造回归 |
| M57 | 消息窗默认隐藏（对齐 Navicat），有消息/结果才显示；消除初始黑色消息区 | ✅ | 隐藏→有消息显示 |
| M58 | 信息面板“选中什么显示什么”（连接/库/表/视图/函数/触发器/列…） | ✅ | 选中联动 + 库信息断言 |
| M59 | 表信息补 列数/索引数；「刷新」保持当前对象；Dock 标题改「信息」 | ✅ | 87 回归 + 打包 r7 |
| M60 | 移除全局固定“查询工具”按钮栏，查询操作移入中央查询工作区 | ✅ | 构造回归 |
| M61 | 查询编辑态专属操作行精简：连接/库 + 保存查询/运行/停止（美化/全部/解释收菜单+快捷键） | ✅ | 87 回归 |
| M62 | 中央区固定第 1 页「对象」（所有功能领域列表态占位），查询子页含新建/删除，双击打开编辑态；编辑动作随当前标签类型显隐 | ✅ | 87 回归 |
| M63 | 表领域「对象」页：随树选中分类切换，表页含 打开/设计/新建/删除表（无导入导出向导），schema_tables 全库批查 | ✅ | 真实 MySQL 冒烟 |
| M64 | 视图领域「对象」页：打开(SHOW CREATE)/新建/删除视图，复用全库表批查过滤 VIEW | ✅ | 真实 MySQL 冒烟 |
| M65 | 函数领域「对象」页（打开 SHOW CREATE/新建向导/删除）+ 移除顶部备份按钮（Navicat 专属格式） | ✅ | 真实 MySQL 冒烟 |
| M66 | 触发器领域「对象」页（打开 SHOW CREATE/删除，无新建入口）+ 收掉顶部 备份/模型/自动运行 按钮与计划任务菜单入口 | ✅ | 真实 MySQL 冒烟 |
| M67 | 「对象」页领域浏览回归测试（ObjectBrowseView 基类 + 查询/表/视图/函数/触发器子页 + 领域切换） | ✅ | 95 回归含真实 MySQL |
| M68 | 「对象」页新增「刷新」按钮，各领域（查询/表/视图/函数/触发器）一键重载列表（对齐 Navicat 刷新） | ✅ | 95 回归 + 刷新信号断言 |
| M69 | 「对象」页选中行联动右侧「信息」面板（表/视图/函数/触发器/查询各自对象信息） | ✅ | 95 回归 + 选中描述断言 |
| M70 | Bugfix：「对象」页按对象树选中库加载（不再用下拉当前库，避免展示错库对象） | ✅ | 95 回归 + 双库不串断言 |
| M71 | PostgreSQL 扩展：连接配置加「数据库类型」，方言 key 贯穿 open/test，PG 驱动 + URL，标准 JDBC 元数据可览库/表 | ✅ | 97 回归 + 真实 PG 15.14 打开/自检/元数据 |
| M72 | PostgreSQL 三级树 db→schema→表/视图/实体化视图/函数/触发器/查询（跨库临时连枚举 schema），MySQL 两级不变 | ✅ | 97 回归 + 真实 PG 树逐级展开 |
| M73 | SQL 转储/运行 SQL 文件 改用 Navicat 风格进度对话框（服务器/库/模式/路径/处理/错误/行/时长 + 日志视图 + 进度条 + 打开） | ✅ | 100 回归 + dump 带 log/progress 回证实 |
| M74 | 连接/对象加载失败改为 MessageBox 弹出 + 树节点折叠（不再用错误占位节点展示），异常前缀清理 | ✅ | 101 回归 + MessageBox/折叠断言 |
| M75 | 对象树展开加载时显示旋转 loading 动画图标（自绘 spinner，加载结束恢复原图标；连接/库/分类/列均接入） | ✅ | 103 回归 + start/stop 图标断言 |
| M76 | 同一对象只开一个标签（Navicat 设定）：查询/视图/函数/触发器重开时定位到已开标签（tab_key 单例），表已有单例 | ✅ | 105 回归 + 单例/不同对象分标签断言 |
| M77 | 「查询」可在 database 级与 schema 级新建：两级右键菜单均有「新建查询」，正确发出 profile_id+database+schema | ✅ | 107 回归 + 两级别 new_query 断言 |
| M78 | 顶部「其它」领域按钮（永驻）：下拉按库型增减，PG 含「序列」（无索引），MySQL 空；序列列表页+编辑/新建对话框（常规字段+SQL预览） | ✅ | 110 回归 + 真实 PG 序列元数据 |
| M79 | Bugfix：「其它」下拉改为 aboutToShow 时按当前连接实时重建（修复连接经树打开/combo未变时 PG 菜单为空） | ✅ | 110 回归 + aboutToShow 含序列断言 |
| M80 | 数据库产品连接图标按 provider_key 区分（devicon 彩色 logo 资产，MIT 许可；缺失回退自绘） | ✅ | 112 回归 + 互异/节点图标断言 |
| M81 | 新建连接改为 Navicat 式两步向导：第1页产品选择（MySQL/MariaDB/PostgreSQL，移除 Oracle 等），第2页按产品定制表单与默认值；编辑锁定产品 | ✅ | 115 回归 + 向导默认值/锁定断言 |
| M82 | Bugfix：PG 表数据全闭环——TableDataApi 标识符/分页/主键按方言（双引号+LIMIT n OFFSET m+pg_index 主键），列元数据走标准 JDBC getColumns，data_table 排序/筛选按方言转义 | ✅ | 116 回归 + 真实 PG 表 CRUD |
| M83 | 日期时间统一显示为 `YYYY-MM-DD HH:MM:SS`（本地时区）：新增 format_datetime，对象页「修改日期」列与结果网格统一接入 | ✅ | 121 回归 + 格式断言 |
| M84 | 数据页加载失败改用 MessageBox 统一报错（清理 Java 前缀）；AGENTS.md 沉淀限定名分隔引号与报错统一约定 | ✅ | 121 回归 |
| M85 | 初版本地存储三合一（历史实现）：连接→注册表、查询内容→.sql 文件、元数据/历史/收藏/设置/片段/任务/窗口状态→SQLite | ✅ | 121 回归（历史记录） |
| M86 | 修复 PG 打开表数据报错：thread 目录级 database(catalog) 到 page/columns/primaryKey/executeScript，PG 下临时连目标库；报错对话框改 error(critical) | ✅ | 121 回归 + 真实 PG 跨库 db3.cicsdev 表 |
| M87 | GaussDB 扩展：PG 兼容对象树/数据页、`jdbc:gaussdb://` 与华为 JDBC 驱动动态加载；「工具 → 环境」指定本机 JAR，驱动不进入发行包 | ✅ | 方言/向导/环境设置/外置 classloader 回归 + openGauss 容器冒烟 |
| M88 | 所有连接选择下拉框统一显示数据库产品图标（主查询栏、备份、任务、导入、传输），共享 profile 填充辅助 | ✅ | 11 项 UI/图标/向导回归 |
| M89 | PG/GaussDB 初始化数据库改为必填且默认 `postgres`；数据库枚举独立查询 `pg_database`，不因初始库隐藏其它库 | ✅ | 向导默认/必填与 GaussDB 元数据回归 |
| M90 | schema 与 table 节点改用高辨识度的 GitHub Ant Design Icons 素材，消除对象树层级图标混淆 | ✅ | 图标非空且互异回归 |
| M91 | SQL 编辑器内核引入 monaco-editor（离线本地资源，QWebEngineView 封装 MonacoEditorWidget，接口兼容 SqlEditorWidget；MAGICCAT_EDITOR=plain 回退自研） | ✅ | 121 回归 + monaco 文本/语句/补全 POC |
| M92 | 当前连接改为「树跟手」+ 查询领域内连接下拉：对象树激活归属连接 → 当前连接变更（无全局当前连接下拉）；查询领域连接选择每标签独立（影响不扩散） | ✅ | 121 回归 + 跟手/标签/每标签连接验证 |
| M93 | 重构「每查询标签一套完整工作区」：QueryWorkspace（连接/库/动作条+编辑器+每标签结果区+状态行，影响不扩散）；查询执行/EXPLAIN/保存查询取当前工作区；对象浏览条（树跟手连接+库）仅对象页显示 | ✅ | 121 回归 + 每标签工作区/对象条可见性验证 |
| M94 | SQL 编辑器上下文对象补全：当前库表/视图/列随上下文弹（FROM/JOIN→表视图、`表.`→列、SELECT/WHERE→列），上下文感知 completion + set_completion_data | ✅ | 121 回归 |
| M95 | 修复 Monaco 上下文补全未生效：等待异步编辑器就绪、provider 单例注册、FROM/JOIN 前缀过滤、PG/GaussDB database→public schema 批查、别名列补全 | ✅ | QWebEngine 实测 FROM/FROM 前缀/schema./表别名. + 2 项回归 |
| M96 | 查询标签页独立 JDBC Catalog/Schema 上下文：MySQL/MariaDB Schema 固定 null，PG/GaussDB 按 Catalog 建连并 setSchema；执行不注入 USE | ✅ | 查询工作区隔离 + QueryService/Java 上下文回归 |
| M97 | 消息/结果区按 Navicat 风格紧凑展开并跟随主题，避免隐藏面板恢复时占满编辑区 | ✅ | 浅色主题颜色 + 首次显示分隔比例回归 |
| M98 | 查询工作区上下文下拉改为纯图标表达；MySQL/MariaDB 隐藏无意义的 Schema 选择器 | ✅ | 图标项 + 无文字标签 + MySQL 隐藏回归 |
| M99 | 修正树跟手边界：左侧树普通选中不再感染已打开查询标签，仅右键“库/模式 → 新建查询”定位新标签 | ✅ | 查询标签上下文隔离 + 右键定位回归 |
| M100 | 收掉对象页全局连接/库选择器；普通新建查询仅在创建瞬间继承左树上下文，创建后标签上下文冻结 | ✅ | 无全局下拉 + 初始化跟手/创建后隔离回归 |
| M101 | 修正新查询初始化竞态：连接下拉填充不再清空右键目标，库/模式级目标在异步加载完成后准确定位 | ✅ | 库级空 Schema + 模式级精确定位回归 |
| M102 | 查询编辑器选中 SQL 时运行按钮改为“运行已选择的”，取消选区恢复默认文案 | ✅ | 纯文本选区 + Monaco 选区状态回归 |
| M103 | Monaco 选区通知改用 `onDidChangeCursorSelection` 原生事件 + QWebChannel，移除 120ms 轮询 | ✅ | 原生事件/桥接静态回归 + M102 选区回归 |
| M104 | 对齐 Navicat：移除“执行全部”，运行无选区执行全文并逐条返回多结果集，有选区只执行选中 SQL | ✅ | 运行文本选择与多语句结果回归 |
| M105 | 表对象页加载错误不再占用删除表旁的上下文栏，改为 `QMessageBox.critical` | ✅ | 表列表加载失败错误框回归 |
| M106 | 修复 GaussDB 表/视图对象页误走 MySQL 反引号查询，改用 Catalog+Schema 标准路径 | ✅ | GaussDB 元数据路由回归 |
| M107 | Monaco 选区事件携带选中文本快照，修复“运行已选择的”按钮正确但仍执行全文 | ✅ | 选区快照桥接回归 |
| M108 | 新增 `scripts/opengauss.ps1`：Podman openGauss 容器创建/启动/停止/日志/gsql/删除助手 | ✅ | 脚本生命周期静态回归 + 本机容器 JDBC 冒烟 |
| M109 | 放开左树/中央/右侧信息三块水平区域的中央最小宽度，非最大化窗口可拖拽调整 dock | ✅ | dock 尺寸策略回归 |
| M110 | 连接/库/模式/表/视图/列基础元数据统一优先走 JDBC `DatabaseMetaData`，MySQL 富字段保留专用路径；GaussDB `getCatalogs` 不完整时定向用 `pg_database` 全量枚举 | ✅ | MySQL + openGauss 临时表/视图/列真实 JDBC 冒烟 + 路由契约回归 |
| M111 | 启动时只显示固定“对象”页，不预建“查询 1”，查询标签按用户操作创建 | ✅ | 初始标签数量与首次新建回归 |
| M112 | 固定“对象”页首屏默认切到“表”工作区，进入表功能域后按 database/schema 加载表列表 | ✅ | 首屏表域与显式加载回归 |
| M113 | 对象工作区无连接上下文时禁用新建/打开/设计/删除/刷新，列表加载成功后恢复操作 | ✅ | 对象按钮上下文状态回归 |
| M114 | 顶部表/视图/函数/查询功能域动作改为互斥选择态，由窗口级当前领域 flag 统一驱动 | ✅ | 功能域动作与当前领域回归 |
| M115 | 表数据页主键读取改用 JDBC `DatabaseMetaData.getPrimaryKeys`，移除 GaussDB 不支持的 `array_position` | ✅ | JDBC 主键路由静态回归 + openGauss 表数据实测 |
| M116 | 修复 GaussDB 序列读取并清理 PG/GaussDB JDBC URL 中误加的 MySQL 超时参数：驱动 `DatabaseMetaData.getTables(..., SEQUENCE)` 枚举名称，openGauss 批量函数补齐富字段；读取失败统一 `QMessageBox.critical` | ✅ | 该驱动真实 JDBC 调用返回序列 + 158 项回归收集 |
| M117 | 固定“对象”页跟随左树连接/库/模式/分类/对象上下文更新；查询标签上下文与当前页保持隔离 | ✅ | 对象页跟手上下文回归 + 查询标签不抢焦点回归 |
| M118 | 修复“其它→序列”未沿用左树上下文：序列入口及刷新/DDL 后重载保持最近 database/schema | ✅ | 序列入口树上下文回归 |
| M119 | GaussDB 序列改为单条 `information_schema`/系统目录批量 SQL，一次返回列表所需字段，移除 JDBC 名称枚举与不兼容的 `LATERAL` 写法 | ✅ | 单 SQL 路由静态回归 + openGauss 7.0 JDBC 实测 |
| M120 | 修复部分 GaussDB 不允许表函数横向引用前置别名：序列当前值/缓存改按 OID 行内读取，保持单条批量 SQL | ✅ | 远端报错定位 + openGauss JDBC 实测 |
| M121 | 修复“设计序列”确定后未执行 SQL：沿用 database/schema 上下文执行 ALTER，写入开始值/当前值并反馈后刷新 | ✅ | 设计提交流程回归 + 序列 SQL 字段回归 |
| M122 | 对齐 Navicat 连接树状态：关闭连接显示灰度产品图标，打开连接恢复彩色；连接右键菜单首项按状态显示「打开连接」/「关闭连接」，查询连接下拉保持彩色 | ✅ | 165 项收集；本次相关回归 7 项通过；Ruff 全绿 |
| M123 | 收敛 JDBC 连接池：长期会话 Hikari 主池上限降为 3 并按需保留空闲连接；连接测试与跨库一次性元数据改用直连，兼容门面同步移除短命池 | ✅ | 169 项收集；池策略/一次性路径回归 4 项通过；Maven package + Ruff |
| M124 | 修复 MySQL 空初始库连接：数据库枚举不再调用 `setCatalog(null)`；明确 database→catalog、schema 永远为 null 的 JDBC 路由约定 | ✅ | MySQL catalog/schema 静态契约 + 连接树聚焦回归；Maven package |
| M125 | 修复 MySQL 标准元数据表列表为空：借出连接后按 database 设置 JDBC catalog，保持 schema 永远为 null | ✅ | 本地 MySQL root 空密码数据库/表元数据回归 + JDBC 路由契约 |
| M126 | 兼容 MySQL 系统库表类型：标准 JDBC 表枚举纳入 `SYSTEM TABLE`，恢复 `mysql.user` 等系统表展示 | ✅ | 本地 MySQL 表/列元数据回归 15 项；Maven package + Ruff |
| M127 | 关闭态连接仅允许定位和查看信息，不激活当前连接及“对象”工作区；打开态保持树跟手 | ✅ | 关闭/打开态对象树信号回归 8 项；Ruff |
| M128 | 连接配置移除 Windows 注册表，改为用户数据目录下按连接名称拆分的版本化 `connections/<连接名称>.json`（密码明文；不兼容旧注册表/JSON，不迁移） | ✅ | JSON 明文回环、原子写入、跨平台目录解析；Ruff |
| M129 | 修复 MySQL JDBC `NULLABLE=YES/NO` 解析导致的数据页加载异常，并将“对象”列表改为 Navicat 式无边框平面表格 | ✅ | Java bridge Maven package；MySQL 可空标志静态回归；对象表格 Qt 回归；Ruff |
| M130 | 左侧对象树表节点暂不展开列明细，保留双击打开表数据及表操作菜单 | ✅ | 表节点无展开指示器/无列子项 Qt 回归；Ruff |
| M131 | “消息”面板按语句记录 SQL、成功/错误状态、影响行数与查询耗时，贴近 Navicat 消息日志 | ✅ | 消息面板 Qt 回归；并发执行消息回归；Ruff |
| M132 | 对象列表双击与左侧树统一走对象定义/数据编辑入口，补齐视图与触发器树侧双击 | ✅ | 对象树双击路由 Qt 回归；Ruff |
| M133 | 引入窗口级不可变 UI 状态容器（typed action/reducer + Qt signal），保留查询工作区标签私有状态边界 | ✅ | 状态 reducer/store 回归；对象页 MySQL catalog 双击回归；Ruff |
| M134 | 收掉 MySQL/MariaDB 连接表单数据库字段，取消对象页初始化库回退，并支持树节点双击直接展开 | ✅ | 对象上下文无默认库回归；连接表单/树双击 Qt 回归；Ruff |
| M135 | 对象页表头增加 Navicat 式字段分隔线，名称列补齐对象图标；用户纳入对象领域并由窗口状态驱动 | ✅ | 对象表头/图标与用户领域切换 Qt 回归；Ruff |
| M136 | 未保存查询标签统一显示“无标题”，使用 UUID 内部 `tab_key` 与显示名解耦 | ✅ | 新查询标题/唯一键 Qt 回归；Ruff |
| M137 | 编辑器标签按内容类型显示对象图标，固定“对象”页图标随当前领域切换 | ✅ | 固定页/查询/对象编辑/表数据标签图标 Qt 回归；Ruff |
| M138 | 引入应用层 Dialect 能力并收口 database/schema 作用域；PG/GaussDB 未激活 schema 不加载表工作区；表数据改为每页 1000 行、当前结果集分页统计与 Navicat 底部 SQL/分页状态栏，移除独立全表计数 | ✅ | 方言/对象上下文/分页 Qt 与静态回归；Java Maven package；Ruff |
| M139 | 对齐 Navicat 数据页底部状态栏分区与空页记录文案；修复新建连接向导第二页标题固定为 MySQL 的问题，标题随产品动态更新 | ✅ | 分页/向导/对象上下文 Qt 回归；Ruff |
| M140 | 按 Navicat 重构连接本地存储为可读连接名 JSON + 独立组索引；未分组连接直挂树根，连接树支持拖拽改组，连接表单移除组字段；连接名称全局唯一且文件名不使用哈希/碰撞后缀 | ✅ | 202 项回归（含可读逐连接明文配置、重复名约束、独立组索引、无注册表路径、连接树分组与拖拽路由）；Ruff |
| M141 | 全局统一错误对话框为 `QMessageBox.critical`；`warning` 仅保留给输入校验类提醒 | ✅ | 202 项回归；Ruff |
| M142 | 连接配置目录按官方 `provider_key` 产品类型分层，形成 `connections/<provider_key>/Servers/<连接名称>.json`（`SQL Server` 保留空格）；不读取旧的扁平连接文件 | ✅ | 产品目录/文件名/重命名路径回归；202 项全量回归；Ruff |
| M143 | 保存查询按 Navicat 连接目录组织：`<产品>/Servers/<连接>/<database>/<schema>/<name>.sql`，MySQL/MariaDB 省略独立 schema 层；SQLite 仅保存索引与作用域元数据 | ✅ | 206 项回归（含 MySQL/PG/SQL Server 路径、对象树与查询工作区作用域）；Ruff |
| M144 | 连接配置文件收纳到连接名称目录，统一使用 `connections/<provider_key>/Servers/<连接名称>/connection.json`；旧的 `Servers/<连接名称>.json` 不读取、不迁移 | ✅ | 连接目录读写、重命名清理、旧扁平路径隔离回归；Ruff |
| M145 | 默认本地数据根目录从应用配置目录迁移到各平台用户文档目录下的 `MagicCat`；保留 `MAGICCAT_HOME` 覆盖，Linux 支持 XDG 用户文档目录 | ✅ | 207 项全量回归（含跨平台路径/XDG 文档目录）；Ruff |
| M146 | 移除连接存储中的 `connections` 中间目录，产品目录直接位于 `MagicCat` 根下，对齐 Navicat 的 `<产品>/Servers/<连接>/connection.json`；旧路径不读取、不迁移 | ✅ | 产品目录、查询目录和旧路径隔离回归；207 项全量回归；Ruff |
| M147 | 连接名称唯一性收窄为同一 `provider_key` 内唯一，不同数据库产品允许使用相同连接名；连接表单即时校验与磁盘加载校验保持一致 | ✅ | 同产品重复名拦截、跨产品同名通过、重命名与目录隔离回归；Ruff |
| M148 | 分组索引改为 Navicat 对齐的 `vgroup.json` 结构：`version: "1.1"`、`vgroups[].vgroup_name/items[]`、顶层 `connections`；分组项按连接名称和产品类型引用，不读取旧 `groups.json` | ✅ | Navicat 结构回归、名称/产品类型引用、重命名后分组引用刷新、旧文件隔离；Ruff |
| M149 | 统一数据库产品 key 为大写（含 `PGSQL`、`MSSQL`），连接配置与查询目录改用方言 `display` 名称；分组文件固定为 `Premium/profiles/vgroup.json`，`server_type` 直接使用大写 key | ✅ | 大写 key 方言/图标/JDBC 回归、display 目录路径、Navicat 分组类型匹配；Ruff |

- 自动化测试：`uv run pytest`（210 passed，含真实 MySQL + PostgreSQL 集成 + Qt offscreen GUI）。
- 每日开发命令与打包命令见 README。

## 附录 C：已确认/解决的问题记录（防回归）

1. **跨线程 Qt 信号丢失**：QRunnable 被回收即销毁信号 QObject → 模块级 `_pending` 持有引用（`ui/job.py`）。
2. **PySide6 6.11 在本机 QtCore DLL 报 procedure-not-found** → 锁定 6.8 LTS（pyproject 注释）。
3. **pytest faulthandler 误报 JVM SEH 访问异常** → `-p no:faulthandler`。
4. **JPype 不自动转换 list→String[]** → 显式 `to_java_string_array()`。
5. **FK 规则列在 REFERENTIAL_CONSTRAINTS**（非 KEY_COLUMN_USAGE）→ LEFT JOIN。
6. **PyInstaller 冻结态资源定位**：`magiccat/resources.py` 按 `_MEIPASS` 解析；JVM/jar 按 `_MEIPASS/jvm`。

---

## 附录 A：待进一步确认的技术细节清单

- [x] PyInstaller + JPype + jlink 的组合打包冒烟（M7a 已通过，见附录 B）
- [ ] JPype 调用长 SQL 时 GIL/线程实测行为（UI 是否全程无感）
- [ ] `stmt.cancel()` 对 mysql-connector-j 的实际效果，是否需要 `KILL QUERY`
- [ ] 大 BLOB / 大文本在 ResultSet 上的取数策略实测
- [ ] Decimal/datetime 在 JPype 自动转换下的精度与时区行为
