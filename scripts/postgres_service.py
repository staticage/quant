"""项目专用 PostgreSQL 服务；不修改系统服务，也不暴露外部网络。

设置 QUANT_DATABASE_URL 可使用已有数据库，此时不自动启动本地服务。
默认集群与私有 Unix socket 均保存在忽略目录，socket 目录仅当前用户可访问。
"""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import shlex
import subprocess

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data/postgres"
SOCKET = ROOT / ".cache/postgres-socket"
PORT = 55432


def binary(name):
    candidates = [Path(os.environ.get("QUANT_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")) / name]
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise RuntimeError("缺少 PostgreSQL 服务端，请安装 postgresql@17 或设置 QUANT_PG_BIN")


def local_dsn(database="quant"):
    return f"dbname={database} user=quant host={SOCKET} port={PORT} connect_timeout=5"


def ensure_local_service():
    """仅自动管理本项目创建的私有集群；已有外部连接完全由用户管理。"""
    SOCKET.mkdir(parents=True, exist_ok=True, mode=0o700)
    SOCKET.chmod(0o700)
    with (ROOT / ".cache/postgres-service.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _start_local_service()


def _start_local_service():
    """文件锁保护初始化与启动，避免两个CLI同时启动/创建数据库。"""
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if not (DATA / "PG_VERSION").exists():
        subprocess.run([binary("initdb"), "-D", str(DATA), "-U", "quant",
                        "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--locale=C"], check=True)
    # pg_ctl 拒绝重复启动同一集群；默认禁用 TCP，只接受私有 socket。
    status = subprocess.run([binary("pg_ctl"), "-D", str(DATA), "status"], capture_output=True)
    if status.returncode:
        subprocess.run([binary("pg_ctl"), "-D", str(DATA), "-l", str(DATA / "server.log"),
                        "-o", f"-k {shlex.quote(str(SOCKET))} -p {PORT} -c listen_addresses=''", "-w", "start"], check=True)
    with psycopg.connect(local_dsn("postgres"), autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'quant'").fetchone():
            conn.execute("CREATE DATABASE quant")


def connect():
    """DSN 不写入日志/审计，防止外部数据库密码进入回测结果。"""
    dsn = os.environ.get("QUANT_DATABASE_URL")
    if not dsn:
        ensure_local_service()
        dsn = local_dsn()
    try:
        conn = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except psycopg.Error:
        raise RuntimeError("PostgreSQL 连接失败，请检查服务与 QUANT_DATABASE_URL 配置") from None
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"], default="start", nargs="?")
    action = parser.parse_args().action
    if action == "start":
        with connect() as conn:
            print("PostgreSQL 已就绪：", conn.execute("SHOW server_version").fetchone()[0])
    else:
        subprocess.run([binary("pg_ctl"), "-D", str(DATA), action], check=True)
