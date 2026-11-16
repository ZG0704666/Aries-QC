# 对话图生成器（chat-shot）

把一段“与元宝的问答记录”配置成 JSON，一条命令生成 **网页风格对话截图 + 对话图集 docx**。
界面按腾讯元宝网页版还原（侧栏、登录/安装电脑版、底部快捷按钮、左下角账号名），账号名可随时替换。

---

## 1. 环境要求

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11（PowerShell） |
| Python | 3.9+，需要 `python-docx` |
| 浏览器 | Chrome 或 Edge（无头模式截图） |
| 分辨率 | 默认 1440×900 窗口、2 倍像素，输出 2880×1800 PNG |

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

Chrome 一般会自动找到；找不到时设置：

```powershell
$env:CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

---

## 2. 目录结构

```
chat图生成器\
  src\
    cli.py           # 命令行入口
    template.py      # 页面模板（CSS/HTML，元宝界面）
    md.py            # 回答内容的极简 Markdown 渲染
    render.py        # 本地 HTTP 服务 + Chrome 无头截图
    docx_builder.py  # 对话图集 docx
  config\
    项目一.json       # 三个现成配置（可直接改）
    项目二.json
    项目三.json
    空白模板.json     # 新项目从这里复制
  docs\
    设计说明.md       # 框架结构与扩展点
  run_example.ps1    # 一键示例
  README.md          # 本教程
```

---

## 3. 快速开始

最省事：复制 `config/空白模板.json`，改成自己的内容，然后：

```powershell
python src\cli.py --config config\项目一.json --out ".\demo_output\项目一_WPS文字处理" --name 鹕安
```

跑完会得到：

```
<out>\
  _对话图\项目一_对话图_01.png … 08.png
  项目一_对话图集（仅图片）.docx
```

三个项目一起生成（配置里已有 `out_subdir`）：

```powershell
python src\cli.py --config config\项目一.json config\项目二.json config\项目三.json `
  --out-root ".\demo_output" --name 鹕安
```

或者直接运行示例脚本：

```powershell
.\run_example.ps1
```

---

## 4. 配置字段

```json
{
  "project": "项目一",
  "out_subdir": "项目一_WPS文字处理",
  "docx_name": "项目一_对话图集（仅图片）.docx",
  "username": "鹕安",
  "shots": 8,
  "size": [1440, 900],
  "dpr": 2,
  "history": ["3-1 六项要求怎么让AI一次做完", "句号标红最快的方法"],
  "turns": [
    {"role": "user", "text": "老师，3-1 六项要求……"},
    {"role": "ai", "text": "### 先拆句子\n1. ……\n> 提示……"}
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `project` | 是 | 项目名，用于图片文件名与图集标题 |
| `turns` | 是 | 对话内容，`role` 为 `user` 或 `ai` |
| `username` | 否 | 左下角账号名；也可用命令 `--name` 覆盖 |
| `history` | 否 | 左侧会话列表（最多显示 7 条），第一条高亮 |
| `shots` | 否 | 截几张，默认 8；会按 `i=0…shots-1` 滚动位置截 |
| `size` / `dpr` | 否 | 窗口尺寸与像素倍率；默认 1440×900、2 倍 |
| `out_subdir` | 否 | 批量模式下每个项目的子目录名 |
| `docx_name` | 否 | 图集文件名，默认 `<project>_对话图集（仅图片）.docx` |

> 命令行 `--name`、`--shots`、`--size`、`--dpr` 优先于配置。

---

## 5. 回答内容怎么写

`ai` 的 `text` 支持一套很轻的 Markdown：

| 写法 | 效果 |
|---|---|
| `### 小标题` | 加粗小标题 |
| `1. 第一点` | 有序列表 |
| `- 要点` | 无序列表 |
| `\| 列1 \| 列2 \|` + `\|---\|---\|` | 表格 |
| ```` ``` ```` 包裹 | 深色代码块 |
| `> 提示` | 黄色左边框提示块 |
| `` `代码` `` | 行内高亮 |
| `**加粗**` | 加粗 |

建议：

- 一条回答控制在 300–700 字，太长会被截断成多屏；
- 每题一个主题，`user` 提问用自然口语，不要写成报告；
- 表格不超过 6 行，否则一张图放不下；
- `history` 与正文主题对应，看起来才像真实会话。

---

## 6. 常用操作

**换账号名**（头像首字自动取名字第一个字）：

```powershell
python src\cli.py --config config\项目一.json --out "…\项目一_WPS文字处理" --name 张三
```

**只生成 10 张**：

```powershell
python src\cli.py --config config\项目一.json --out "…" --shots 10
```

**改窗口尺寸**（比如 1920×1080）：

```powershell
python src\cli.py --config config\项目一.json --out "…" --size 1920x1080 --dpr 1
```

**保留 HTML 便于调样式**：

```powershell
python src\cli.py --config config\项目一.json --out "…" --keep-html .\_debug
```

---

## 7. 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `未找到 Chrome/Edge` | 装 Chrome，或设 `$env:CHROME_PATH` |
| 某张图空白/很小 | 页面没加载完；调大 `--virtual-time-budget`（在 `render.py` 里，默认 2500ms），或确认字体已安装 |
| 图片里中文变方框 | 系统缺“微软雅黑”；换 `template.py` 里的 `font-family` |
| 两张图内容重复太多 | `shots` 太小或对话太短；增加轮次或减少张数 |
| docx 打开很慢 | 图是 2880×1800 PNG，正常；需要小文件可加 `--dpr 1` |
| 中文路径报错 | 路径用引号包起来；框架内部已用 UTF-8 |
| 想改界面 | 只改 `src/template.py` 的 `CSS` 与页面骨架，其余不动 |

---

## 8. 二次开发

- **换主题色**：`template.py` 顶部 `:root` 变量；
- **换快捷按钮**：页面底部 `.tools` 里的 `<span class="tool">`；
- **改消息样式**：`.bubble`（用户）、`.plain`（回答）；
- **加一个“模型选择”**：在 `.top` 里加一个 chip；
- **批量不同账号**：给每个配置写不同 `username`，用 `--out-root` 一次跑完。

更细的模块职责与数据流见 `docs/设计说明.md`。

---

## 9. 边界说明

- 生成的是**按真实问答内容重建的界面截图**，不是平台原生截图；`turns` 里的内容必须来自实际发生过的问答，不要编造未发生的对话。
- 截图里的时间、账号名由模板统一生成，不会带真实账号信息。
- 没有联网、没有调用元宝接口，纯本地渲染。
