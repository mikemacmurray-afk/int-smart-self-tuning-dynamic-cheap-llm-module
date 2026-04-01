"""Storage backend implementations."""

from smart_llm.storage.base import StorageBackend


def create_storage(backend: str, **kwargs) -> StorageBackend:
    """Factory: create a storage backend by name.

    Args:
        backend: One of "sqlite", "mysql", "json"
        **kwargs: Backend-specific arguments (path, url, etc.)

    Returns:
        An initialized StorageBackend instance.
    """
    if backend == "sqlite":
        from smart_llm.storage.sqlite_backend import SQLiteBackend
        return SQLiteBackend(**kwargs)
    elif backend == "mysql":
        from smart_llm.storage.mysql_backend import MySQLBackend
        return MySQLBackend(**kwargs)
    elif backend == "json":
        from smart_llm.storage.json_backend import JSONBackend
        return JSONBackend(**kwargs)
    else:
        raise ValueError(f"Unknown storage backend: '{backend}'. Must be one of: sqlite, mysql, json")


__all__ = ["StorageBackend", "create_storage"]
