"""
Generate docs pages automatically.
Based on https://mkdocstrings.github.io/recipes/#generate-pages-on-the-fly
"""

from pathlib import Path

import mkdocs_gen_files

MODULE_NAME = "ipod"

root = Path(__file__).parent.parent
module_path = root / MODULE_NAME

for path in sorted(module_path.rglob("*.py")):
	doc_path = path.relative_to(root).with_suffix(".md")
	if doc_path.stem == "__init__":
		doc_path = doc_path.with_stem("index")
		continue  # actually, let's just ignore __init__ files, i don't store any logic in them.
	full_doc_path = Path("reference", doc_path)

	parts = tuple(path.relative_to(root).with_suffix("").parts)

	if parts[-1] == "__init__":
		parts = parts[:-1]
	elif parts[-1] == "__main__":
		continue

	with mkdocs_gen_files.open(full_doc_path, "w") as fd:
		identifier = ".".join(parts)
		print(f"""\
---
title: {parts[-1]}
---
::: {identifier}""", file=fd)

	mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))
