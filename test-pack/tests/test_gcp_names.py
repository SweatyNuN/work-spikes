from __future__ import annotations

from testpack.gcp_names import last_segment, parse_network_attachment, parse_subnet


def test_parse_full_network_attachment():
    value = "projects/demo/regions/europe-west2/networkAttachments/vertex-psc-attachment"

    reference = parse_network_attachment(value)

    assert reference.project == "demo"
    assert reference.region == "europe-west2"
    assert reference.name == "vertex-psc-attachment"
    assert reference.attachment_name == value


def test_parse_network_attachment_url():
    value = (
        "https://www.googleapis.com/compute/v1/projects/demo/regions/"
        "europe-west2/networkAttachments/vertex-psc-attachment"
    )

    reference = parse_network_attachment(value)

    assert reference.name == "vertex-psc-attachment"
    assert reference.region == "europe-west2"


def test_parse_attachment_bare_name_with_defaults():
    reference = parse_network_attachment(
        "vertex-psc-attachment",
        project="demo",
        region="europe-west2",
    )

    assert reference.name == "vertex-psc-attachment"
    assert reference.attachment_name == (
        "projects/demo/regions/europe-west2/networkAttachments/vertex-psc-attachment"
    )


def test_parse_region_qualified_attachment():
    reference = parse_network_attachment(
        "regions/europe-west2/networkAttachments/vertex-psc-attachment",
        project="demo",
    )

    assert reference.project == "demo"
    assert reference.region == "europe-west2"
    assert reference.name == "vertex-psc-attachment"


def test_parse_subnet_self_link():
    value = (
        "https://www.googleapis.com/compute/v1/projects/demo/regions/"
        "europe-west2/subnetworks/vertex-psc-subnet"
    )

    reference = parse_subnet(value)

    assert reference.project == "demo"
    assert reference.region == "europe-west2"
    assert reference.name == "vertex-psc-subnet"


def test_parse_subnet_name_without_project():
    reference = parse_subnet("vertex-psc-subnet", region="europe-west2")

    assert reference.project is None
    assert reference.region == "europe-west2"
    assert reference.name == "vertex-psc-subnet"


def test_last_segment():
    assert last_segment("projects/p/global/networks/vpc") == "vpc"
    assert last_segment("vpc/") == "vpc"
