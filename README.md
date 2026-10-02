
整理小学语文教材PDF以输出结构化数据的工具。

附有一个基于这些数据的「小学语文教材字词工具」静态网页，功能有：

* 生字检查：检查文章中的字是否已经在指定范围的教材中学过、写过；
* 组词：从指定范围的教材和词语表中给一个字组词，结果分成最后一课（正在学习）、倒数第二第三课（近期复习）和其他三桶，按词频降序排列。
* 打印书写纸：生成描红练习纸 PDF（A4／A5 横竖版，田字格／米字格等，可选课次字词或手动输入）。字体来自本机系统楷体，推荐 Chrome / Edge；详见网页「打印书写纸」→「正文字体」说明。

支持**按学期批次**入库与**成套教材**切换：每学期一批文本；网页按学生成套路径（上一批一上 ↔ 下一批一下）拼装并切换数据。

## 安装

```bash
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

- Python 3.10+
- 转换 PDF 须预先安装 `pdftotext`
- 网页导出组词分词：`pip install -e ".[web]"`（或 `pip install jieba`）

## 目录约定

```
material/{批次ID}/     # 如 2026-04-02、2026-09-16；放该学期 PDF 与版式 .md
output/{批次ID}/       # 该批解析结果（历史批保留，勿删）
tmp/parse-scratch/     # --scratch 兼容性测试输出（不覆盖正式 output）
configs/books.yaml     # 槽位级默认（b11…b62 的栏数、extractors_drop 等）
configs/batches.yaml   # 可选；批次清单与启用状态
configs/active_sources.yaml  # 当前允许正式解析的教材路径白名单
configs/defaults.yaml  # 提取器共用参数
```

批次 ID 为 `YYYY-MM` 或 `YYYY-MM-DD`。册次按文件名中的「一年级上册」…「六年级下册」关键词识别，完整文件名可变。

**批次惯例**：每学期一批；下半年批次多为各年级**上册**，上半年批次多为各年级**下册**（不必凑齐 12 册）。

**成套与界面**：用户可选的锚点**只来自最新一批**中实际有的册（如当前最新为 `2026-09-16` 上册，则可选「2026一上」…「2026六上」）。成套向历史批错位回溯（上一批一上 ↔ 下一批一下）；锚定之后的学期空缺为正常；应有之批缺册时顶替，下拉标「有替换」，并在页面顶部提示条写明教材替换情况。

**当前解析白名单**：`configs/active_sources.yaml` 列出正在核对的版式文件（或批次目录）。启用后，`convert` / `extract` / `toc-chunk` 默认**只允许**写入与这些文件相关的正式数据；其它册会被拒绝或跳过，以免覆盖已核对结果。对历史批做兼容性测试时请加 `--scratch`，结果写入 `tmp/parse-scratch/{batch}/`。

```bash
# 查看当前白名单
python -m textbook_parser active --project-root .

# 正式解析（须在白名单内）
python -m textbook_parser extract --book b11 --extractor 识字表 --project-root .

# 兼容性测试：不改正式 output
python -m textbook_parser extract --book b11 --batch 2025-12-01 --extractor 识字表 --scratch --project-root .
```

## 每学期更新步骤

1. 新建 `material/{新日期}/`，放入本学期 PDF（及/或已转换的版式 `.md`）。
2. 若只有 PDF，先转换版式文本（默认只处理**最新一批**）：

```bash
python -m textbook_parser convert-all --project-root .
# 或指定批次
python -m textbook_parser convert-all --project-root . --batch 2026-09-16
```

3. 对该批提取并分块：

```bash
python -m textbook_parser extract-all --extractor 目录 --project-root .
python -m textbook_parser extract-all --extractor 识字表 --project-root .
python -m textbook_parser extract-all --extractor 写字表 --project-root .
python -m textbook_parser extract-all --extractor 词语表 --project-root .
python -m textbook_parser toc-chunk --project-root . --books --continue-on-error

```

4. 导出网页数据（汇总**所有**已解析批次并生成成套目录）：

```bash
python scripts/export_web_data.py
```

5. 打开 `web/index.html`，在顶部「教材套」中选择成套（如 `2026五下`）。

日常命令省略 `--batch` 时等价于 `--batch latest`（最新一批）。历史批可用 `--batch 2026-04-02` 重跑。输出默认写入 `output/{batch}/`。

## 配置

默认设置见 `configs/defaults.yaml`。

书册槽位配置见 `configs/books.yaml`（与批次无关）。

可选 `configs/batches.yaml` 登记批次顺序；也可用扫描 `material/` 下日期目录自动发现。

当前正在解析的教材路径见 `configs/active_sources.yaml`（白名单；`enabled: true` 时生效）。

## pdftotext !!! 小心覆盖，注意备份

```bash
# 转换最新一批 books.yaml 中本批有文件的书目
python -m textbook_parser convert-all --project-root .

# 只转换一册
python -m textbook_parser convert --book b12 --project-root .

# 只转换多册
python -m textbook_parser convert-all --project-root . --books b12,b21,b32
```

某册若在单书 YAML 里做了额外覆盖，仍可使用：

```bash
python -m textbook_parser convert --config configs\b12.yaml
```

等价于：

```bash
pdftotext -enc UTF-8 -layout <源.pdf> <输出.txt 或 .md>
```

### 旁路模式（不覆盖正式 Markdown）

识字表/写字表可改用内容流顺序（`raw`）或阅读顺序拆栏（`default`），写入旁路 `.raw.txt` / `.default.txt` 或 `--scratch`，**不会改正式 `.md`**：

```bash
# 仅表页试转（页码按 PDF）
python -m textbook_parser convert --book b11 --batch 2026-09-16 --text-mode raw --first-page 110 --last-page 113 --scratch --project-root .
python -m textbook_parser convert --book b11 --batch 2026-09-16 --text-mode default --first-page 110 --last-page 113 --scratch --project-root .

# 从旁路文本提取（结果建议也用 --scratch）
python -m textbook_parser extract --book b11 --batch 2026-09-16 --extractor 写字表 --text-mode raw --scratch --project-root .
python -m textbook_parser extract --book b11 --batch 2026-09-16 --extractor 识字表 --text-mode default --scratch --project-root .
```

经验（一上 b11）：写字表用 `raw`（先左栏后右栏）更顺；识字表用 `default` 更稳。`raw` 提取前会把「一字一行 + 拼音」折叠成现有解析器可用的块。

## 按配置从 md 中提取到 JSON

```bash
# 最新一批：每种提取器各跑一次
python -m textbook_parser extract-all --extractor 目录 --project-root .
python -m textbook_parser extract-all --extractor 识字表 --project-root .
python -m textbook_parser extract-all --extractor 写字表 --project-root .
python -m textbook_parser extract-all --extractor 词语表 --project-root .

# 指定书册提取全部提取器
python -m textbook_parser extract --book b12 --project-root .

# 指定多册同一提取器
python -m textbook_parser extract-all --extractor 识字表 --project-root . --books b12,b21,b32
```

## 按目录分块，保存为 JSON

运行前须确认版式文件已存在，且 `output/{batch}/{book_code}_目录.json` 已生成。

```bash
python -m textbook_parser toc-chunk --project-root . --books
python -m textbook_parser toc-chunk --project-root . --book b12
python -m textbook_parser toc-chunk --project-root . --books b12,b21,b31
python -m textbook_parser toc-chunk --project-root . --book b31 --output output
python -m textbook_parser toc-chunk --project-root . --book b31 --body-start-line 126
python -m textbook_parser toc-chunk --project-root . --books --continue-on-error
```

## 导出到 web 应用数据

```bash
python scripts/export_web_data.py
python scripts/export_web_data.py --output web/generated/data.js
```

**打印书写纸／PDF 必须通过本地 HTTP 打开**（直接双击 `web/index.html` 会因浏览器 CORS 拦截 ES 模块而失败）。

Windows 可双击项目根目录的 `start-web.bat`（自动启动服务并打开浏览器）。或手动：

```bash
python -m http.server 8080 --directory web
# 访问 http://localhost:8080/
```

## TODO

* [ ] 分块文本的进一步结构化
    * [ ] 提取课文
* [ ] 人工分类核对数据，并加以固定
* [ ] 完善部分新批次版式中识字表等附录的提取（源文本缺表或标题版式异常时）
