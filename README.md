# 常用命令

```bash
python -m textbook_parser extract-all --extractor 目录 --project-root . 
python -m textbook_parser extract-all --extractor 识字表 --project-root . 
python -m textbook_parser extract-all --extractor 写字表 --project-root . 
python -m textbook_parser extract-all --extractor 词语表 --project-root . 

#分切
python -m textbook_parser toc-chunk --project-root . --books
# 可选：--output output --project-root . --body-start-line 126 --books --book b31
```

# textbook-parser

将教材 PDF 用命令行工具 `pdftotext` 转为**保留版式**的纯文本，再按**每本书、每种解析类型**的 YAML 配置切分并提取为结构化数据（如 JSON）。

全书使用 **`configs/books.yaml` 中的 `book_code`**（如 `b12`）标识书目，**不再**使用拼音式 `pdf_id`。

## 环境要求

- Python 3.10+
- [Poppler](https://poppler.freedesktop.org/) 提供的 `pdftotext`，且在系统 `PATH` 中可执行（Windows 下多为 `poppler-xx/bin`）

## 安装

在项目根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

## 书目代码（`configs/books.yaml`）

顶层键 `book_code` 将**短代码**映射为 `material/` 下的 **PDF 文件名**（仅文件名，不含目录）。工具会默认推导：

- `source_pdf` → `material/<文件名>`
- `layout_text` → `material/text-by-layout/<文件名去后缀>.md`

若实际路径不同，可在单书 YAML 中**显式**写 `source_pdf` / `layout_text` 覆盖上述默认。

新增书目：先在 `books.yaml` 的 `book_code` 下增加一行，再新建 `configs/bXX.yaml`（或任意文件名）并设置相同的 `book_code`。

## 工作流程

### 1. 准备 PDF 与配置

- 将 PDF 放到 `material/`，文件名与 `configs/books.yaml` 中对应代码一致。
- 在 `configs/` 下为该书建 YAML（示例：`configs/b12.yaml`），**必须**含 `book_code`，并与 `books.yaml` 中的键一致。

### 2. 生成版式文本（pdftotext）

等价于：

```text
pdftotext -enc UTF-8 -layout <源.pdf> <输出.txt 或 .md>
```

通过本工具：

```powershell
python -m textbook_parser convert --config configs\b12.yaml
```

- 默认输出路径由 `book_code` 与 `books.yaml` 推导；也可在单书 YAML 里写死 `layout_text`。
- `pdftotext` 小节可改 `enc`、`layout`，或增加 `extra_args` 传给 `pdftotext`。

### 3. 按配置提取 JSON

```powershell
python -m textbook_parser extract --config configs\b12.yaml
```

- 默认运行该配置中的**全部**提取器；只跑一种时：

  ```powershell
  python -m textbook_parser extract --config configs\b12.yaml --extractor 识字表
  ```

- 结果目录默认为项目根下 `output/`，可改：

  ```powershell
  python -m textbook_parser extract --config configs\b12.yaml --output output
  ```

- 命名规则：`{book_code}__{提取器名}.json`（例如 `b12__识字表.json`）。

也可安装入口脚本（若已 `pip install -e .`）：

```powershell
textbook-parser convert --config configs\b12.yaml
textbook-parser extract --config configs\b12.yaml
```

## 单书配置文件说明（YAML）

| 字段 | 含义 |
|------|------|
| `book_code` | **必填**，与 `configs/books.yaml` 中 `book_code` 下的键一致 |
| `source_pdf` | 可选；默认 `material/<books.yaml 中该代码对应的文件名>` |
| `layout_text` | 可选；默认 `material/text-by-layout/<PDF 主文件名>.md` |
| `pdftotext` | `enc`、`layout`、`extra_args` |
| `extractors` | 各提取器名称（自定义）→ 模块与切分标记 |

每个提取器下常用字段：

| 字段 | 含义 |
|------|------|
| `module` | 内置解析模块名，当前支持 `char_tables`（识字表 / 写字表版式） |
| `start_line_pattern` | 字符串或列表；**整行**匹配（见下） |
| `end_line_pattern` | 同上；切片**不含**该行，但该行原文会用于匹配 `total_pattern` 并写入 `total_note` |
| `unit_head_pattern` | 字符串或列表；**行首**匹配（见下）。汉字行若以此开头，视为**新表块**并对应 TOC 下一条；否则该拼音–汉字块归入**上一单元**（`lesson`/`garden` 从上一数据行继承） |
| `discard_line_patterns` | 字符串或列表；**整行**匹配；命中行抛弃，并在**标准错误输出**打印原文供核对 |
| `TOC_of_unit` | 课文目录顺序列表，与 **`unit_head_pattern` 锚点行**一一对应（见下） |
| `options` | 传给该模块的选项（见下） |
| `start_markers` / `end_markers` | （旧版）子串包含匹配；与 `start_line_pattern` 二选一 |

**匹配前预处理**：先去掉**制表符** `\t`，再对用于 `start_line_pattern`、`end_line_pattern`、`discard_line_patterns` 以及 `options.total_pattern` 的字符串去掉其余空白得到紧凑串，并做 `re.fullmatch`。拼音、汉字解析也在去 `\t` 后的行上进行。

**`unit_head_pattern`**：将列表中各项用 `|` 拼成**一个**行首正则，对紧凑串做 `re.match`（非整行）。**匹配**则该行为新表块起点（消费一条 `TOC_of_unit`）；**不匹配**视为版式**换行续写**，并入**上一条数据组**（`chars`、`pinyin` 追加，`hanzi_line` 用换行拼接），不单独成行、不单独占一个 unit。随后仍会把 `lesson`、`garden` 从上一组继承到逻辑上需要的字段（锚点行已含课号/园地时无需再抄）。文末若剩一段拼音无对应汉字行，会并入上一行的 `pinyin`。无法解析的汉字行会将拼音并入上一行并仍打印该行。

**抛弃行日志**：凡被抛弃的行（**含 `discard_line_patterns` 整行匹配**、版式噪音、`total_pattern` 正文内命中、解析跳过等），除**空行**外，均在标准错误输出**原样**打印该行全文（仅前缀 `[book_code/提取器 抛弃] `）。其中 **`discard_line_patterns` 优先于 `total_pattern`** 判定，以免被后者先处理。`TOC` 对不齐等仍单独带 `[… TOC]` 前缀提示。

**`TOC_of_unit`**：按教材顺序列出每条课文或园地。与 **`unit_head_pattern` 是否匹配该行汉字**对齐：匹配则消费下一条目录；不匹配则沿用上一单元的 `unit`。写入每行的 `unit` 对象；`lesson`/`garden` 字段另会从上一数据行**继承**以便筛选。若目录条数与「锚点」行数不一致，会有 `toc_warnings`。顶层 `units_from_toc` 为目录解析副本。YAML 中每条建议带引号，如 `"1 春夏秋冬"`。

`char_tables` 的 `options` 示例：

| 选项 | 含义 |
|------|------|
| `total_pattern` | 正则，对**紧凑整行** `fullmatch`；用于结束行（切片边界）与正文内偶发重复说明；匹配成功写入 `total_note` |
| `expected_char_count` | 可选；若设置且与逐行合计字数不一致，会在控制台与 JSON 中给出提示 |

新版式：可复制 `configs/b12.yaml`，改 `book_code` 与各正则。若规则完全不同，可在 `src/textbook_parser/extractors/` 增加模块并在 `extractors/__init__.py` 的 `REGISTRY` 中注册，然后把 `module` 改为新名。

## JSON 输出结构（`char_tables`）

每条顶层对象大致包含：

- `book_code`、`extractor`
- `rows`：数组，每项一行教材表格式块，字段包括：
  - `section`：`识字` 或 `阅读`（由版式中的小节标题推断）
  - `lesson`：课序号；园地条目为 `null`；**续行**与上一数据行相同
  - `garden`：园地序号汉字；课文条目为 `null`；**续行**与上一数据行相同
  - `chars`：**数组**，每项为**字典**：`char`（汉字）、`pinyin`（由版式编码按映射表转换的**带调**拼音）、`polyphone`（多音字等，当前默认 `false`）。汉字个数与 `pinyin_line` 按空格切分后的词数不一致时，向 stderr 打印提示
  - `pinyin_line`：该数据组内**整段版式拼音**（保持原文不转换；空格分词与 `chars` 顺位对应；换行续写拼在同一字符串里）
  - `hanzi_line`：汉字行原文（去 `\t` 后）；若有换行续写并入同组，为多行以 `\n` 拼接
  - `unit`：若配置了 `TOC_of_unit`，为对应课文/园地的结构化信息（续行与上一锚点行相同）
- `units_from_toc`：配置了 `TOC_of_unit` 时存在，为全部目录项的解析结果
- `toc_alignment`：配置了 `TOC_of_unit` 时存在，含 `toc_catalog_count`（目录条数）、`toc_anchor_group_count`（锚点数据组条数）、`toc_one_to_one_ok`（是否一一对应）。每项提取结束时会向**标准输出**打印同一核对结论
- `toc_warnings`：目录与锚点行数量不一致等问题时出现
- `total_note`：匹配 `total_pattern` 的整行说明（若有）
- `char_count_computed`：所有 `chars` 数组长度之和（每个字典计 1 字）
- `char_count_warning`：仅当配置了 `expected_char_count` 且不一致时出现

### 识字表字数说明（`b12` 等）

一年级下册识字表脚注规定：表中**蓝色多音字**在此处**不计入**教材所统计的「生字总数」。因此 JSON 中逐字合计（如 419）可能大于文末「共 410 个生字」；属正常现象。该册配置中**未**设置 `expected_char_count`，避免误报。写字表可与 `expected_char_count: 200` 对齐校验。

## 各册命令汇总

```powershell
# !!! 转换后要手动清理双栏的情况
# python -m textbook_parser convert --config configs\b11.yaml
python -m textbook_parser extract --config configs\b11.yaml
python -m textbook_parser convert --config configs\b12.yaml
python -m textbook_parser extract --config configs\b12.yaml
python -m textbook_parser convert --config configs\b21.yaml
python -m textbook_parser extract --config configs\b21.yaml
python -m textbook_parser convert --config configs\b22.yaml
python -m textbook_parser extract --config configs\b22.yaml
python -m textbook_parser convert --config configs\b31.yaml
python -m textbook_parser extract --config configs\b31.yaml
python -m textbook_parser convert --config configs\b32.yaml
python -m textbook_parser extract --config configs\b32.yaml

```