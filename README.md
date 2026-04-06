
整理小学语文教材PDF以输出格式化数据的的工具。

## 安装

```bash
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

- Python 3.10+
- 转换文件须预先安装 `pdftotext`

## 配置

默认设置见`configs/defaults.yaml`

书册相关配置见`configs/books.yaml`

将 PDF 放到 `material/`，文件名与 `configs/books.yaml` 中对应代码一致。

## pdftotext

```bash
# 转换 books.yaml 中全部书目（每个 PDF → material/text-by-layout/ 下对应版式文件）
python -m textbook_parser convert-all --project-root .

# 只转换一册（book_code 与 configs/books.yaml 一致）
python -m textbook_parser convert --book b12 --project-root .

# 只转换多册（逗号分隔 book_code）
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

## 按配置从md中提取到JSON

```bash
# 从所有书册提取全部类别：每种提取器各跑一次 extract-all（须已有版式文本，缺则先 convert-all）
python -m textbook_parser extract-all --extractor 目录 --project-root .
python -m textbook_parser extract-all --extractor 识字表 --project-root .
python -m textbook_parser extract-all --extractor 写字表 --project-root .
python -m textbook_parser extract-all --extractor 词语表 --project-root .

# 从指定书册提取全部提取器（该册配置里的每一项都会跑）
python -m textbook_parser extract --book b12 --project-root .

# 从指定书册只跑某一提取器
python -m textbook_parser extract --book b12 --extractor 识字表 --project-root .

# 从指定多册各跑一次同一提取器（逗号分隔 book_code）
python -m textbook_parser extract-all --extractor 识字表 --project-root . --books b12,b21,b32
```

## 按目录分块，保存为JSON

运行前须先确认版式文件已存在，目录文件`output/{book_code}_目录.json`已经。

```bash
# 书目表中全部书册（仅写 --books，后面不写列表）
python -m textbook_parser toc-chunk --project-root . --books

# 指定一册
python -m textbook_parser toc-chunk --project-root . --book b12

# 指定多册（逗号分隔 book_code）
python -m textbook_parser toc-chunk --project-root . --books b12,b21,b31

# 输出目录（相对项目根，默认 output）
python -m textbook_parser toc-chunk --project-root . --book b31 --output output

# 强制正文起始行（0 基，即 splitlines 后的行号）；省略则用「独占一行的第×单元」启发式
python -m textbook_parser toc-chunk --project-root . --book b31 --body-start-line 126

# 批量时某一册失败仍继续其余册
python -m textbook_parser toc-chunk --project-root . --books --continue-on-error
```
