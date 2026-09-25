# database 文件夹

存放 **SQLite 数据库**相关的所有东西。

## 文件说明

| 文件 | 作用 | 要不要提交到 Git |
| --- | --- | --- |
| `schema.sql` | **表结构设计**（四张表的建表语句） | ✅ 要，这是源码 |
| `init_db.py` | 建表脚本，读取 `schema.sql` 并执行 | ✅ 要 |
| `migrate.py` | **升级脚本**：把旧版 `dialogues` 搬成新的 `sessions` + `messages` | ✅ 要 |
| `backup/` | 迁移前自动生成的数据库备份 | ❌ 不要（已在 `.gitignore` 里忽略） |
| `zhixue.db` | 数据库本体，运行时自动生成 | ❌ 不要（已在 `.gitignore` 里忽略） |

## 我该用哪个脚本？

| 你的情况 | 用哪个 |
| --- | --- |
| 全新开始（数据库里没有 `dialogues` 表） | `init_db.py` |
| 从 v0.4 或更早升级上来（有 `dialogues` 表） | **`migrate.py`** |

> 其实**平时都用不着手动跑** —— 后端启动时会自动建表。
> 只有"升级"这件事必须手动做一次。

## init_db.py —— 建表

```powershell
cd D:\0\1
python database\init_db.py
```

输出：

```
数据库初始化完成！

数据库文件：D:\0\1\database\zhixue.db
已有的表（共 4 张）：
  - messages
  - reports
  - sessions
  - students
```

这个脚本**可以反复运行**，因为建表语句都带了 `IF NOT EXISTS`，不会删数据。

## migrate.py —— 升级

```powershell
cd D:\0\1
python database\migrate.py
```

会先问你一句「确定要继续吗？」，输入 `y` 回车即可。
想跳过确认（比如写自动化脚本时）用 `python database\migrate.py --yes`。

它做三件事：

1. 把整个数据库文件备份到 `database/backup/zhixue_backup_时间戳.db`
2. 旧表 `dialogues` **改名**为 `dialogues_backup_时间戳`（是改名，不是删除）
3. 把旧数据搬进新表：**每条旧记录 → 1 个会话 + 2 条消息**

整个过程包在一个事务里，中途出错会**自动回滚**，数据库还是原来的样子。

**可以重复运行吗？** 可以。搬过一次之后 `dialogues` 表就不存在了，
再运行会直接提示「无需迁移」。

## 四张表的关系

```
students (学生)
   │  id
   ├──────────────< sessions (会话)          一个学生有多个会话
   │                   id
   │                   └──< messages (消息)  一个会话有多条消息
   │                            id
   └──────────────< reports  (学习报告)
                      student_id
```

一个学生 → 多个会话 → 每个会话多条消息。
删掉学生时，他的会话、消息、报告都会跟着一起删（`ON DELETE CASCADE`）；
删掉会话时，里面的消息也会一起删。

## 关于 SQLite 的小知识

- SQLite **不需要安装**任何数据库软件，也不用启动服务。
- Python 自带 `sqlite3` 模块，直接就能用。
- 数据库就是一个 `.db` 文件，删掉就等于清空所有数据（开发阶段很方便）。
- ⚠️ SQLite 默认**不检查外键**！每次建立连接后都要手动执行一次
  `PRAGMA foreign_keys = ON`，这个已经写在 `backend/db.py` 里了。

## 改表结构时注意

`CREATE TABLE IF NOT EXISTS` 的意思是"表已存在就跳过"。
所以**给已有的表加字段**时，光改 `schema.sql` 再重启是没用的，字段加不上去。

两种解决办法：

1. **数据不要了**：删掉 `zhixue.db`，重启后端。
2. **保留数据**：临时在 `schema.sql` 里加一句
   `ALTER TABLE students ADD COLUMN grade TEXT;`，
   重启一次执行完，再把这句删掉。

> 如果以后改动越来越大，最好照 `migrate.py` 的样子**再写一个迁移脚本**：
> 备份 → 建新结构 → 搬数据 → 旧表改名。这样永远不会丢数据。
