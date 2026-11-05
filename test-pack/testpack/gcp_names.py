"""Parsing for Google Cloud resource names used by the PSC checks.

The same resource can be written several ways in Terraform outputs, gcloud
output and config files:

    vertex-psc-attachment
    regions/europe-west2/networkAttachments/vertex-psc-attachment
    projects/my-project/regions/europe-west2/networkAttachments/vertex-psc-attachment
    https://www.googleapis.com/compute/v1/projects/.../networkAttachments/...

Normalising in one place keeps the checkers and the pipeline plugin
consistent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NETWORK_ATTACHMENT = re.compile(
    r"(?:projects/(?P<project>[^/]+)/)?"
    r"(?:regions/(?P<region>[^/]+)/)?"
    r"networkAttachments/(?P<name>[^/]+)"
)
_SUBNET = re.compile(
    r"(?:projects/(?P<project>[^/]+)/)?"
    r"(?:regions/(?P<region>[^/]+)/)?"
    r"subnetworks/(?P<name>[^/]+)"
)


@dataclass(frozen=True)
class ResourceRef:
    name: str
    project: str | None = None
    region: str | None = None

    @property
    def attachment_name(self) -> str | None:
        if self.project and self.region:
            return f"projects/{self.project}/regions/{self.region}/networkAttachments/{self.name}"
        return None


def _parse(
    value: str, pattern: re.Pattern[str], project: str | None, region: str | None
) -> ResourceRef:
    text = str(value).strip()
    match = pattern.search(text)
    if match:
        return ResourceRef(
            name=match.group("name"),
            project=match.group("project") or project,
            region=match.group("region") or region,
        )
    return ResourceRef(name=text.rsplit("/", 1)[-1], project=project, region=region)


def parse_network_attachment(
    value: str,
    project: str | None = None,
    region: str | None = None,
) -> ResourceRef:
    return _parse(value, _NETWORK_ATTACHMENT, project, region)


def parse_subnet(
    value: str,
    project: str | None = None,
    region: str | None = None,
) -> ResourceRef:
    return _parse(value, _SUBNET, project, region)


def last_segment(value: object) -> str:
    """Return the trailing name from a URL, self-link or bare name."""
    return str(value).rstrip("/").rsplit("/", 1)[-1]
