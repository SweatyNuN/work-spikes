from google.cloud import aiplatform

aiplatform.init(project="my-project", location="europe-west2")

model = aiplatform.Model("projects/123/locations/europe-west2/models/456")

print("Artifact URI:", model.artifact_uri)
