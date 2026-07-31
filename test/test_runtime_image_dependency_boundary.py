from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def requirement_names(path: str) -> set[str]:
    return {
        line.split("==", 1)[0].split(">=", 1)[0].strip().lower()
        for line in read(path).splitlines()
        if line.strip() and not line.startswith("-")
    }


def test_pilot_runtime_does_not_install_local_embedding_stack() -> None:
    runtime_requirements = requirement_names("requirements.txt")

    assert not {
        "sentence-transformers",
        "transformers",
        "huggingface-hub",
        "safetensors",
    } & runtime_requirements


def test_local_embedding_stack_is_an_explicit_opt_in() -> None:
    optional_requirements = ROOT / "requirements-local-embedding.txt"

    assert optional_requirements.is_file()
    optional_packages = requirement_names("requirements-local-embedding.txt")
    assert "-r requirements.txt" in read("requirements-local-embedding.txt")
    assert {
        "sentence-transformers",
        "transformers",
        "huggingface-hub",
        "safetensors",
    } <= optional_packages


def test_pilot_and_vision_dockerfile_dependency_boundaries_remain_separate() -> None:
    pilot_dockerfile = read("Dockerfile")
    runpod_vision_dockerfile = read("deploy/runpod-vision/Dockerfile")
    aws_vision_dockerfile = read("deploy/aws-vision/Dockerfile")

    assert "-r requirements.txt" in pilot_dockerfile
    assert "requirements-local-embedding.txt" not in pilot_dockerfile
    assert "requirements-vision-runpod.txt" in runpod_vision_dockerfile
    assert "FROM pytorch/pytorch:" in aws_vision_dockerfile
    assert "requirements-vision-runpod.txt" in aws_vision_dockerfile


def test_readme_marks_local_embedding_install_as_optional() -> None:
    readme = read("README.md")

    assert "requirements-local-embedding.txt" in readme
    assert "선택" in readme
