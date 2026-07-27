import google.cloud.aiplatform as aiplatform

endpoint = aiplatform.Endpoint("projects/123/locations/europe-west2/endpoints/456")

response = endpoint.predict(
    instances=[
        {"feature_1": 0.3, "feature_2": 12, "feature_3": "segment_a"},
    ]
)

print(response.predictions)
