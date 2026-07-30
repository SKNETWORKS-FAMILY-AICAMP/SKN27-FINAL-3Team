"""Container entrypoint for the private AWS Vision worker."""

from app.services.aws_vision_worker import main


if __name__ == "__main__":
    main()
