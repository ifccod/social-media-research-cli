PYTHON ?= python3

.PHONY: help install test test-python test-extension docs docs-check \
	session-start session-status session-stop browser-start session-restart

help:
	@printf '%s\n' \
		'install         安装本机 Python 包' \
		'test            运行 Python、扩展和生成文档检查' \
		'test-python     运行 Python 测试套件' \
		'test-extension  运行浏览器扩展合同测试' \
		'docs            根据 argparse 重新生成 skill/SKILL.md' \
		'docs-check      检查生成的 Skill 是否与代码一致' \
		'session-start   启动或复用本地浏览器桥接进程' \
		'session-status  查看本地浏览器桥接进程状态' \
		'session-stop    停止本地浏览器桥接进程' \
		'browser-start   session-start 的兼容别名' \
		'session-restart 重启本地浏览器桥接进程'

install:
	$(PYTHON) -m pip install -e .

test: test-python test-extension docs-check

test-python:
	$(PYTHON) -m unittest discover -s test -t . -v

test-extension:
	cd browser_session_bridge && npm test

docs:
	$(PYTHON) -m reverse describe --format skill --output skill/SKILL.md

docs-check:
	$(PYTHON) -c 'from pathlib import Path; from reverse.catalog import render_skill; path = Path("skill/SKILL.md"); assert path.read_text(encoding="utf-8") == render_skill(), "skill/SKILL.md 已与代码不一致，请运行 make docs"'

session-start:
	$(PYTHON) -m reverse session start

session-status:
	$(PYTHON) -m reverse session status

session-stop:
	$(PYTHON) -m reverse session stop

browser-start: session-start

session-restart: session-stop session-start
