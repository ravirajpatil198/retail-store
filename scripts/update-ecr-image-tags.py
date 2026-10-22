import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: update-ecr-image-tags.py <ecr-registry> <image-tag>")

    registry, image_tag = sys.argv[1:]
    if not re.fullmatch(r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com", registry):
        raise SystemExit("Invalid ECR registry")
    if not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?",
        image_tag,
    ):
        raise SystemExit(
            "Image tag must be SemVer MAJOR.MINOR.PATCH with an optional prerelease"
        )

    for service in ("ui", "catalog", "cart", "checkout", "orders"):
        path = Path("src") / service / "chart" / "values.yaml"
        content = path.read_text(encoding="utf-8")
        repository_pattern = re.compile(r"(?m)^  repository:.*$")
        tag_pattern = re.compile(r"(?m)^  tag:.*$")
        if len(repository_pattern.findall(content)) != 1 or len(tag_pattern.findall(content)) != 1:
            raise SystemExit(f"Expected one application image repository and tag in {path}")

        content = repository_pattern.sub(
            f"  repository: {registry}/retail-store-{service}", content, count=1
        )
        content = tag_pattern.sub(f'  tag: "{image_tag}"', content, count=1)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
