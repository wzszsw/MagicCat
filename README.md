# MagicCat

对标 Navicat 的跨数据库桌面管理工具。技术栈：**PySide6（界面） + JPype（内嵌 JVM） + JDBC（数据访问）**，首发支持 MySQL / MariaDB，配置存储遵循 Windows/macOS/Linux 用户文档目录约定。

详细设计见 [docs/MagicCat设计方案.md](docs/MagicCat设计方案.md)。

## 第三方素材与商标说明

项目使用的外部图标来源、版本和许可记录见 [引用素材清单](docs/引用素材.md)。项目自有代码的开源许可不替代第三方素材各自适用的许可条款。

- GaussDB 连接图标使用 [Simple Icons 的 Huawei SVG](https://github.com/simple-icons/simple-icons/blob/develop/icons/huawei.svg)，本地资产为 [huawei.svg](magiccat/resources/logos/huawei.svg)，许可文本见 [SIMPLE_ICONS_LICENSE.md](magiccat/resources/logos/SIMPLE_ICONS_LICENSE.md)。该许可仅涉及版权及相关权利，不代表取得 Huawei 商标授权。
- MySQL、PostgreSQL、MariaDB 连接图标来自 [Devicon](https://github.com/devicons/devicon)，许可文本见 [LICENSE.txt](magiccat/resources/logos/LICENSE.txt)。
- database 图标来自 [Tabler Icons](https://github.com/tabler/tabler-icons)，许可文本见 [TABLER_LICENSE](magiccat/resources/icons/TABLER_LICENSE)；schema/table 图标来自 [Ant Design Icons](https://github.com/ant-design/ant-design-icons)，许可文本见 [ANT_DESIGN_LICENSE](magiccat/resources/icons/ANT_DESIGN_LICENSE)。

Huawei、GaussDB、MySQL、PostgreSQL、MariaDB 及上述图标库名称和标识归各自权利人所有。MagicCat 是独立开源项目，与相关厂商或图标库不存在隶属、授权、赞助或官方背书关系；这些名称和图标仅用于标识连接类型或兼容对象。

## 工程体系（Python 主流方案）

| 文件/目录 | 作用 |
|---|---|
| `pyproject.toml` | 工程元数据 + 依赖声明（≈ Node 的 package.json） |
| `uv.lock` | 精确依赖锁（≈ package-lock.json，由 uv 生成） |
| `.venv/` | 虚拟环境（不进版本库） |
| `java-bridge/` | Maven 工程，JVM 内 JDBC 数据访问层（HikariCP + mysql-connector-j） |
| `magiccat/` | Python 主包（UI / bridge 封装 / services 门面） |
| `scripts/` | 开发辅助脚本 |

## 环境要求

- Python ≥ 3.12（本机：miniforge 3.12.12）
- Java 17（本机：Temurin 17，`JAVA_HOME` 已设置）
- Maven 3.6+
- uv（依赖/虚拟环境管理）

## 快速开始

```powershell
# 1) 构建 Java 数据访问层
.\scripts\build_java.ps1

# 2) 安装 Python 依赖（自动创建 .venv 并生成 uv.lock）
uv sync --extra dev

# 3) 运行 M1 技术验证 POC（连接本机 MySQL，需 127.0.0.1:3306 root/空密码）
uv run python scripts/poc_m1.py

# 4) 运行应用入口（当前为占位输出）
uv run magiccat
```

## 常用开发命令

```powershell
uv add <包名>          # 新增运行时依赖
uv run pytest          # 运行测试
uv run ruff check .    # 静态检查
uv run python -m magiccat
```

## openGauss 本机联调

项目提供 Podman 助手脚本，默认使用 `magiccat-opengauss`、`docker.io/library/opengauss:6.0.3` 和宿主机 `15432` 端口：

```powershell
.\scripts\opengauss.ps1                         # 创建或启动容器
.\scripts\opengauss.ps1 -Action status         # 查看状态
.\scripts\opengauss.ps1 -Action logs           # 查看最近日志
.\scripts\opengauss.ps1 -Action gsql           # 进入 gsql
.\scripts\opengauss.ps1 -Action stop           # 停止但保留容器
.\scripts\opengauss.ps1 -Action remove -Force  # 明确确认后删除容器
```

默认 JDBC 地址为 `jdbc:gaussdb://127.0.0.1:15432/postgres`，用户为 `gaussdb`；密码可通过 `-GaussPassword` 覆盖。GaussDB JDBC 驱动仍需在 MagicCat「工具 → 环境」中手动指定，不随项目分发。

## 里程碑

见设计方案 §10。当前进度（自动化测试 23+ 项，另含打包产物 `--selftest`）：

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 | 技术验证：PySide6→JPype→HikariCP→MySQL 全链路 POC | ✅ |
| M2 | 连接管理（跨平台 JSON 明文配置）+ 对象浏览 | ✅ |
| M3 | SQL 编辑器（高亮/补全/多标签/历史/美化）+ 多结果集 | ✅ |
| M4 | 数据页（分页/主键编辑/增删行）+ 表设计器（ALTER 预览） | ✅ |
| M5 | 导入导出 CSV/Excel/JSON/SQL | ✅ |
| M6a | 主题、ER 图、SQL 备份/恢复、收藏/复制打磨 | ✅ |
| M7a | Windows 打包：PyInstaller + jlink 内嵌 JRE（`--selftest` 通过，免装 Java） | ✅ |
| M151 | Windows 完整发行构建：强制重建 bridge/应用，正式版 `--windowed`，自检后编译 Inno 安装器 | ✅ |
| 剩余 | 计划任务/i18n、更多细节 | 后续 |

## 打包

```powershell
.\scripts\build_windows.ps1            # 完整发行构建：重建 bridge/应用、自检、便携 ZIP、Inno 安装器
.\scripts\build_windows.ps1 -SkipJlink # 完整构建，但复用已有内嵌 JRE
.\scripts\build_package.ps1              # 调试构建（带控制台，便于查看异常栈）
.\scripts\build_package.ps1 -Windowed   # 发布构建（无控制台窗口）
.\scripts\build_package.ps1 -SkipJlink   # 复用已有内嵌 JRE 快速重打
.\dist\MagicCat\MagicCat.exe --selftest  # 打包自检（无需系统 Java）
```

完整发行构建会先重建 Java bridge，再以无控制台模式生成应用本体，最后编译 `dist\installer\MagicCat-Setup-<版本>.exe`；不要直接对旧的 `dist\MagicCat` 目录运行 Inno Setup。
