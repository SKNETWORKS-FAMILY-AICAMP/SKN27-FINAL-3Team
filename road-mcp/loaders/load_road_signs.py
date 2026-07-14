from loaders.common import ensure_data_dirs, print_not_implemented


def main() -> None:
    ensure_data_dirs()
    print_not_implemented("road guide signs loader")


if __name__ == "__main__":
    main()
