from app.bootstrap.migration import SchemaMigrationRunner, run_migration


def main() -> None:
    run_migration()


if __name__ == "__main__":
    main()
