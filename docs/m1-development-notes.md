# M1 Development Notes

状态：进行中。M1 目标是建立可持续开发的 monorepo 工程骨架。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M1-01 创建 monorepo 目录 | Done | `apps/`, `packages/`, `docs/`, `tests/` |
| M1-02 初始化 Python 包管理 | Done | `pyproject.toml` |
| M1-03 初始化 `yourvpn-core` | Done | `packages/python/yourvpn-core/src/yourvpn_core` |
| M1-04 初始化 FastAPI app | Done | `apps/api/src/yourvpn_api/main.py` |
| M1-05 初始化 Worker app | Done | `apps/worker/src/yourvpn_worker/main.py` |
| M1-06 初始化 wg-agent app | Done | `apps/wg-agent/src/yourvpn_wg_agent/main.py` |
| M1-07 初始化 Vue + TypeScript app | Done | `apps/frontend` |
| M1-08 建立配置加载和环境变量约定 | Done | `.env.example`, `yourvpn_core.config` |
| M1-09 建立统一日志格式 | Done | `yourvpn_core.logging` |
| M1-10 建立 pytest、前端 lint/build | Done | `python -m pytest`, `npm.cmd run lint`, `npm.cmd run build` |

## Local Commands

Python tests:

```bash
python -m pytest
```

API:

```bash
$env:PYTHONPATH="packages/python/yourvpn-core/src;apps/api/src"
python -m uvicorn yourvpn_api.main:app --host 127.0.0.1 --port 8008
```

Worker:

```bash
$env:PYTHONPATH="packages/python/yourvpn-core/src;apps/worker/src"
python -m yourvpn_worker.main --once
```

wg-agent:

```bash
$env:PYTHONPATH="packages/python/yourvpn-core/src;apps/wg-agent/src"
python -m uvicorn yourvpn_wg_agent.main:app --host 127.0.0.1 --port 8009
```

Frontend:

```bash
cd apps/frontend
npm.cmd install
npm.cmd run lint
npm.cmd run build
```

## 2026-06-26 Validation Run

- `python -m pytest` passed: 9 tests.
- `python -m yourvpn_worker.main --once` returned worker health JSON.
- API `GET /health` returned service `api`.
- wg-agent `GET /health` returned service `wg-agent` and `database_access=false`.
- `npm.cmd install` completed far enough to create `node_modules` and `package-lock.json`; the initial shell command timed out while waiting, but subsequent frontend commands used the installed dependencies successfully.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.

## Running Development Servers

Initial M1 validation used the first local development ports. Current M8+ defaults are:

- API: `http://127.0.0.1:8008/health`
- wg-agent development health app: `http://127.0.0.1:8009/health`
- Frontend: `http://127.0.0.1:5566/`

Logs are written under `.m1-out/logs`.
