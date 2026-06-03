from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


COLD_TRUNCATION_TABLES = [
    "ab_test_sample",
    "agent_execution_events",
    "analysis_finding",
    "blocked_challenges",
    "cached_container_images",
    "capability_gap_plans",
    "executions",
    "improvement_attempt",
    "topology_change_log",
    "artifact_schemas",
    "user_settings",
    "reports",
    "relations",
    "skill_bindings",
    "skill_build_attempts",
    "orchestration_telemetry",
    "execution_telemetry",
    "facts",
    "hypotheses",
    "agents_version",
    "prompts_version",
    "skills_version",
    "transaction",
    "ab_test",
    "agents",
    "skills",
    "prompts",
    "package_mappings",
    "research_cache",
]

QDRANT_COLLECTIONS = ["shared_memory_facts", "shared_memory_hypotheses"]

VECTOR_SIZE = 768
QDRANT_PAYLOAD_INDEXES = [
    "source_agent_id",
    "execution_id",
    "project_id",
    "created_at_ts",
    "confidence",
    "tags",
]


def parse_pg_url(database_url: str) -> dict:
    """Extract connection parameters from a SQLAlchemy-style database URL.

    Handles both ``postgresql+asyncpg://`` and ``postgresql://`` prefixes.
    """
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username or "lumari",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "lumari",
    }


async def cold_reset(
    database_url: str | None = None,
    qdrant_url: str | None = None,
    skip_seed: bool = False,
    skip_qdrant: bool = False,
    dry_run: bool = False,
) -> dict:
    """Transactional cold reset: truncate all tables, clear Qdrant, re-seed.

    Returns a summary dict.
    """
    db_url = database_url or settings.database_url
    qd_url = qdrant_url or settings.qdrant_url
    summary: dict = {"tables_truncated": 0, "qdrant_cleared": [], "agents_seeded": 0}

    if dry_run:
        logger.info("[DRY RUN] Would truncate tables: %s", COLD_TRUNCATION_TABLES)
        if not skip_qdrant:
            logger.info("[DRY RUN] Would clear Qdrant collections: %s", QDRANT_COLLECTIONS)
        if not skip_seed:
            logger.info("[DRY RUN] Would re-seed agents from seed_agents.py")
        summary["dry_run"] = True
        return summary

    engine = create_async_engine(db_url, echo=False)
    try:
        summary["tables_truncated"] = await _truncate_all_tables(engine)
    finally:
        await engine.dispose()

    if not skip_qdrant:
        summary["qdrant_cleared"] = _clear_qdrant_collections(qd_url)

    if not skip_seed:
        engine = create_async_engine(db_url, echo=False)
        try:
            summary["agents_seeded"] = await _seed_from_default(engine)
        finally:
            await engine.dispose()

    logger.info("Cold reset complete: %s", json.dumps(summary, indent=2))
    return summary


async def _truncate_all_tables(engine) -> int:
    """Truncate all tables in a single transaction. Returns count of tables."""
    async with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "postgresql":
            table_list = ", ".join(COLD_TRUNCATION_TABLES)
            await conn.execute(text(f"TRUNCATE {table_list} CASCADE"))
            logger.info("Truncated %d tables (PostgreSQL TRUNCATE CASCADE)", len(COLD_TRUNCATION_TABLES))
        else:
            for table_name in COLD_TRUNCATION_TABLES:
                try:
                    await conn.execute(text(f"DELETE FROM {table_name}"))
                except Exception:
                    pass
            logger.info("Deleted from %d tables (SQLite fallback)", len(COLD_TRUNCATION_TABLES))
    return len(COLD_TRUNCATION_TABLES)


def _clear_qdrant_collections(qdrant_url: str) -> list[str]:
    """Delete and recreate shared memory Qdrant collections with indexes."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

    client = QdrantClient(url=qdrant_url)
    cleared = []

    for collection_name in QDRANT_COLLECTIONS:
        if client.collection_exists(collection_name):
            client.delete_collection(collection_name)
            logger.info("Deleted Qdrant collection: %s", collection_name)

        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )

        for field_name in QDRANT_PAYLOAD_INDEXES:
            schema = PayloadSchemaType.KEYWORD
            if field_name in ("created_at_ts", "confidence"):
                schema = PayloadSchemaType.FLOAT
            try:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=schema,
                )
            except Exception as e:
                logger.debug("Index creation skipped for %s: %s", field_name, e)

        cleared.append(collection_name)
        logger.info("Recreated Qdrant collection: %s (with %d indexes)", collection_name, len(QDRANT_PAYLOAD_INDEXES))

    client.close()
    return cleared


async def _seed_from_default(engine) -> int:
    """Re-seed initial agents and prompts from seed_agents.py definitions."""
    from scripts.seed_agents import create_agent_with_prompt
    from app.orchestration.agents.definitions import load_agents_by_team

    async_session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    count = 0

    async with async_session() as session:
        for agent_data in load_agents_by_team("main_team"):
            try:
                _, status = await create_agent_with_prompt(session, agent_data, "main_team")
                if status == "created":
                    count += 1
            except Exception as e:
                logger.warning("Seed skipped %s: %s", agent_data["name"], e)
                await session.rollback()

        for agent_data in load_agents_by_team("developer_team"):
            try:
                _, status = await create_agent_with_prompt(session, agent_data, "developer_team")
                if status == "created":
                    count += 1
            except Exception as e:
                logger.warning("Seed skipped %s: %s", agent_data["name"], e)
                await session.rollback()

    logger.info("Seeded %d agents", count)
    return count


def warm_snapshot_save(
    output_path: str,
    database_url: str | None = None,
    qdrant_url: str | None = None,
) -> dict:
    """Create pg_dump snapshot + Qdrant snapshots for warm restart.

    Returns paths to saved artifacts.
    """
    db_url = database_url or settings.database_url
    qd_url = qdrant_url or settings.qdrant_url
    params = parse_pg_url(db_url)
    result = {"pg_dump": None, "qdrant_snapshots": []}

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if _pg_tool_available_locally("pg_dump"):
        env = {**os.environ, "PGPASSWORD": params["password"]}
        cmd = [
            "pg_dump",
            "--host", params["host"],
            "--port", str(params["port"]),
            "--username", params["user"],
            "--dbname", params["dbname"],
            "--format=custom",
            "--file", output_path,
        ]
        logger.info("Running local: %s", " ".join(cmd))
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed (exit {proc.returncode}): {proc.stderr}")
    elif _docker_container_running(POSTGRES_CONTAINER):
        container_path = f"/tmp/warm_snapshot.dump"
        dump_cmd = [
            "docker", "exec", POSTGRES_CONTAINER,
            "pg_dump",
            "--username", params["user"],
            "--dbname", params["dbname"],
            "--format=custom",
            "--file", container_path,
        ]
        logger.info("Running in Docker: %s", " ".join(dump_cmd))
        proc = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump (docker) failed (exit {proc.returncode}): {proc.stderr}")
        cp_cmd = ["docker", "cp", f"{POSTGRES_CONTAINER}:{container_path}", output_path]
        subprocess.run(cp_cmd, check=True, capture_output=True, timeout=60)
    else:
        raise RuntimeError(
            "'pg_dump' not found locally and Docker container "
            f"'{POSTGRES_CONTAINER}' is not running."
        )

    result["pg_dump"] = output_path
    logger.info("pg_dump saved to: %s", output_path)

    for collection in QDRANT_COLLECTIONS:
        try:
            resp = httpx.post(f"{qd_url}/collections/{collection}/snapshots", timeout=60)
            if resp.status_code == 200:
                snap_info = resp.json().get("result", {})
                result["qdrant_snapshots"].append(
                    {"collection": collection, "snapshot": snap_info.get("name", "unknown")}
                )
                logger.info("Qdrant snapshot created for %s: %s", collection, snap_info.get("name"))
            else:
                logger.warning("Qdrant snapshot failed for %s: %s", collection, resp.text)
        except Exception as e:
            logger.warning("Qdrant snapshot skipped for %s: %s", collection, e)

    logger.info("Warm save complete: %s", json.dumps(result, indent=2))
    return result


def warm_snapshot_restore(
    snapshot_path: str,
    database_url: str | None = None,
) -> dict:
    """Restore database from pg_dump snapshot.

    Returns summary dict.
    """
    db_url = database_url or settings.database_url
    params = parse_pg_url(db_url)

    if not Path(snapshot_path).exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

    if _pg_tool_available_locally("pg_restore"):
        env = {**os.environ, "PGPASSWORD": params["password"]}
        cmd = [
            "pg_restore",
            "--host", params["host"],
            "--port", str(params["port"]),
            "--username", params["user"],
            "--dbname", params["dbname"],
            "--clean", "--if-exists", "--no-owner",
            "--format=custom",
            snapshot_path,
        ]
        logger.info("Running local: %s", " ".join(cmd))
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    elif _docker_container_running(POSTGRES_CONTAINER):
        container_path = "/tmp/warm_restore.dump"
        cp_cmd = ["docker", "cp", snapshot_path, f"{POSTGRES_CONTAINER}:{container_path}"]
        subprocess.run(cp_cmd, check=True, capture_output=True, timeout=60)
        cmd = [
            "docker", "exec", POSTGRES_CONTAINER,
            "pg_restore",
            "--username", params["user"],
            "--dbname", params["dbname"],
            "--clean", "--if-exists", "--no-owner",
            "--format=custom",
            container_path,
        ]
        logger.info("Running in Docker: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    else:
        raise RuntimeError(
            "'pg_restore' not found locally and Docker container "
            f"'{POSTGRES_CONTAINER}' is not running."
        )

    if proc.returncode != 0:
        if "FATAL" in proc.stderr or "could not connect" in proc.stderr:
            raise RuntimeError(f"pg_restore failed (exit {proc.returncode}): {proc.stderr}")
        logger.warning("pg_restore warnings: %s", proc.stderr)

    logger.info("Warm restore complete from: %s", snapshot_path)
    return {"restored_from": snapshot_path, "returncode": proc.returncode}


POSTGRES_CONTAINER = "lumari-postgres"


def _pg_tool_available_locally(tool_name: str) -> bool:
    """Check if pg_dump/pg_restore is available on the local PATH."""
    try:
        subprocess.run([tool_name, "--version"], capture_output=True, check=True)
        return True
    except FileNotFoundError:
        return False


def _docker_container_running(container: str) -> bool:
    """Check if a Docker container is running."""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0 and "true" in proc.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="F18 — Cold/Warm DB switch for evaluation runs",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    cold_p = subparsers.add_parser("cold", help="Truncate all tables + re-seed")
    cold_p.add_argument("--skip-seed", action="store_true", help="Don't re-seed after truncation")
    cold_p.add_argument("--skip-qdrant", action="store_true", help="Don't clear Qdrant collections")
    cold_p.add_argument("--database-url", default=None, help="Override database URL")
    cold_p.add_argument("--qdrant-url", default=None, help="Override Qdrant URL")
    cold_p.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    save_p = subparsers.add_parser("warm-save", help="Snapshot current DB state")
    save_p.add_argument("--output", required=True, help="Path for pg_dump output file")
    save_p.add_argument("--database-url", default=None, help="Override database URL")
    save_p.add_argument("--qdrant-url", default=None, help="Override Qdrant URL")

    restore_p = subparsers.add_parser("warm-restore", help="Restore DB from snapshot")
    restore_p.add_argument("--snapshot", required=True, help="Path to pg_dump snapshot file")
    restore_p.add_argument("--database-url", default=None, help="Override database URL")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == "cold":
        asyncio.run(cold_reset(
            database_url=args.database_url,
            qdrant_url=args.qdrant_url,
            skip_seed=args.skip_seed,
            skip_qdrant=args.skip_qdrant,
            dry_run=args.dry_run,
        ))

    elif args.command == "warm-save":
        warm_snapshot_save(
            output_path=args.output,
            database_url=args.database_url,
            qdrant_url=getattr(args, "qdrant_url", None),
        )

    elif args.command == "warm-restore":
        warm_snapshot_restore(
            snapshot_path=args.snapshot,
            database_url=args.database_url,
        )


if __name__ == "__main__":
    main()
