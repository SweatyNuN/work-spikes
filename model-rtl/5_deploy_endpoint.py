vertex_model.deploy(
    endpoint=endpoint,
    deployed_model_display_name="churn-classifier-v1",
    machine_type="n1-standard-4",  # or g2-standard-8 / a2-highgpu-1g for LLMs
    min_replica_count=1,
    max_replica_count=3,
    traffic_percentage=100,
)
