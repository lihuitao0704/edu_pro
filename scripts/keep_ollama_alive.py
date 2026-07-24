"""
Ollama Embedding 服务守护脚本
============================
用途: 部署在 Ollama 同机器上（或可 SSH 到 Ollama 的机器），挂了就自动拉起。
依赖: Python 3.8+（仅标准库，无需 pip install）

用法:
  # 前台运行（查看日志）
  python scripts/keep_ollama_alive.py

  # 后台运行（Linux）
  nohup python scripts/keep_ollama_alive.py > /tmp/ollama_guard.log 2>&1 &

  # 配合 crontab（每 2 分钟兜底检查，即使守护进程本身挂了也能恢复）
  */2 * * * * * /usr/bin/python3 /path/to/scripts/keep_ollama_alive.py --once >> /tmp/ollama_guard.log 2>&1
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

# ── 配置（按你的环境修改） ──────────────────────────────────
OLLAMA_URL = os.getenv("OLLAMA_EMBED_URL", "http://192.168.0.100:11434")
MODEL = os.getenv("OLLAMA_MODEL", "bge-m3")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))      # 秒，轮询间隔
RESTART_COOLDOWN = int(os.getenv("RESTART_COOLDOWN", "60"))  # 秒，重启冷却防疯狂重启
PROBE_TEXT = "ping"

# Ollama 服务管理命令（按部署方式二选一）
#   systemd 方式（推荐，如果 ollama 由 systemd 管理）:
OLLAMA_RESTART_CMD = os.getenv("OLLAMA_RESTART_CMD", "systemctl restart ollama")
#   直接二进制方式（如果是手动启动的）:
# OLLAMA_RESTART_CMD = "nohup ollama serve > /tmp/ollama.log 2>&1 &"


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [ollama-guard] {msg}"
    print(line, flush=True)


def check_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """TCP 端口探测"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_embedding_api() -> bool:
    """真正调一次 embedding，确认服务可用"""
    url = f"{OLLAMA_URL}/api/embed"
    payload = json.dumps({"model": MODEL, "input": [PROBE_TEXT]}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return bool(data.get("embeddings"))
    except Exception:
        return False


def restart_ollama() -> None:
    """拉起 Ollama 服务"""
    log(f"正在重启 Ollama: {OLLAMA_RESTART_CMD}")
    try:
        result = subprocess.run(
            OLLAMA_RESTART_CMD,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log("重启命令已执行，等待服务就绪...")
        else:
            log(f"重启命令返回非零: rc={result.returncode} stderr={result.stderr[:200]}")
    except Exception as e:
        log(f"重启失败: {e}")


def wait_for_recovery(max_wait: int = 120) -> bool:
    """等待 Ollama 恢复，最多等 max_wait 秒"""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if check_embedding_api():
            log("Ollama 已恢复")
            return True
        time.sleep(5)
    log(f"Ollama 在 {max_wait}s 内未恢复")
    return False


def run_once() -> bool:
    """执行一次检查，返回 True 表示服务正常"""
    if check_embedding_api():
        return True

    log(f"Embedding 接口不可用: {OLLAMA_URL}")

    # 进一步判断：端口通但 API 不通 → 进程异常；端口不通 → 进程挂了
    try:
        from urllib.parse import urlparse
        parsed = urlparse(OLLAMA_URL)
        host, port = parsed.hostname, parsed.port or 11434
    except Exception:
        host, port = "127.0.0.1", 11434

    if check_port_open(host, port):
        log(f"端口 {port} 开放但 embedding API 异常，可能模型未加载")
    else:
        log(f"端口 {port} 关闭，Ollama 进程已退出")

    restart_ollama()
    return wait_for_recovery()


def run_loop() -> None:
    """持续守护"""
    log(f"启动 Ollama 守护 | url={OLLAMA_URL} | model={MODEL} | interval={CHECK_INTERVAL}s")
    last_restart = 0.0
    while True:
        try:
            if not run_once():
                # 重启后仍未恢复，进入冷却
                now = time.time()
                if now - last_restart < RESTART_COOLDOWN:
                    log("冷却中，跳过频繁重启")
                last_restart = now
        except Exception as e:
            log(f"守护循环异常: {e}")
        time.sleep(CHECK_INTERVAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama 服务守护脚本")
    parser.add_argument("--once", action="store_true", help="仅检查一次（适合 crontab）")
    args = parser.parse_args()

    if args.once:
        ok = run_once()
        sys.exit(0 if ok else 1)
    else:
        run_loop()


if __name__ == "__main__":
    main()
