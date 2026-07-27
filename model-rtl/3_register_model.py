from google.cloud import aiplatform

project_id = "my-project"
location = "europe-west2"  # or your region

aiplatform.init(project=project_id, location=location)

vertex_model = aiplatform.Model.upload(
    display_name="churn-classifier-2026-07-27",
    artifact_uri="gs://production-ml-artifacts-my-project/models/churn/2026-07-27/",
    serving_container_image_uri=(
        "europe-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-0:latest"
    ),
)
