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
| 连接管理（多库、分组、加密保存、测试连接） | 支持（分组树 + 主密码/DPAPI 加密） | M2 |
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

- 查询返回 `ResultPage{ columns, rows(可空值标记), total, hasMore, truncated }`。
- 前端网格采用**服务端分页**：`LIMIT offset,size`（MySQL 方言由 `MySqlDialect` 生成，包住用户原始 SQL 时使用子查询包裹，保证 ORDER BY 正确）。
- 行数估算：`SELECT COUNT(*)` 单独执行并缓存给状态栏；超大表上可降级为"仅提示已加载行数"。
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
| ConnectionManager | `ConnectionService` + `profiles.json` 加密存储 | 分组树、复制连接、测试连接、批量导入连接配置 |
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
| 连接口令存储 | `profiles.json`（含连接配置、分组、口令密文）；密文 = AES-256-GCM，密钥二选一：<br>① 用户设置主密码 → PBKDF2-HMAC-SHA256(≥210k 次) 派生；<br>② 未设主密码 → Windows DPAPI（`CryptProtectData`，绑定当前用户） |
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
4. 安装器：Inno Setup —— 装到 `%LocalAppData%\Programs\MagicCat`，写开始菜单/桌面快捷方式，卸载清理 `%APPDATA%\MagicCat` 用户数据除外。
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
| M2 | 连接管理（DPAPI 加密）+ 对象浏览 | ✅ | pytest：加密回环 / 元数据 / Qt 对象树异步加载 |
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

- 自动化测试：`uv run pytest`（100 passed，含真实 MySQL + PostgreSQL 集成 + Qt offscreen GUI）。
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
