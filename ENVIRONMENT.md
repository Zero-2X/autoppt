# 运行环境

建议在 Windows + Microsoft PowerPoint 环境运行正式质量门禁；没有 PowerPoint COM 导出时，Gold release 必须保持 blocked。

```powershell
cd D:\onlyppt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

也可以使用 `environment.yml` / `environment.lock.yml` 创建 Conda 环境。Node.js/PptxGenJS 用于部分 editable composer；正式运行前执行：

```powershell
python autopptskills/scripts/check_editable_backends.py --json-out .codex-tmp/method-capabilities.json
```

