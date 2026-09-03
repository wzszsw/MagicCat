# MagicCat

对标 Navicat 的跨数据库桌面管理工具。技术栈：**PySide6（界面） + JPype（内嵌 JVM） + JDBC（数据访问）**，首发支持 MySQL / MariaDB，目标平台 Windows。

详细设计见 [docs/MagicCat设计方案.md](docs/MagicCat设计方案.md)。

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

## 里程碑

见设计方案 §10：M0 方案 ✔ → M1 技术验证（本阶段）→ M2 连接与对象浏览 → M3 SQL 开发闭环 → … → M7 打包发布。
