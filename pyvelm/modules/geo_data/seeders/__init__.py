"""Registered seeders for the ``geo_data`` module (auto-discovered by the loader)."""
from .geography import GeographyDatabaseSeeder

SEEDERS = [GeographyDatabaseSeeder]

__all__ = [
    "GeographyDatabaseSeeder",
    "SEEDERS",
]
