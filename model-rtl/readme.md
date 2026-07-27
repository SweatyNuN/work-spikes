Stage	What you do	Vertex AI piece	Typical interface
1. Discover / design	Pick base model or define custom	Model Garden / your code	Console, SDK, notebooks
2. Train / fine-tune	Run training or tuning jobs	Training / Tuning / Pipelines	SDK, pipelines, Terraform
3. Register model	Store artifact + metadata	Vertex AI Model Registry	SDK, REST, Terraform
4. Deploy to endpoint	Attach model to compute	Online Endpoints / Inference Service	SDK, REST, Terraform
5. Invoke / integrate	Call endpoint from apps	HTTPS endpoint / client libs	REST, client SDKs
6. Govern / upgrade	Versioning, aliases, retirement	Model lifecycle (Gemini, etc.)	Registry + docs


The general flow of model registry is as follows

- Bring in a model you want to train against
- Do the training and output a pkl or some kind of model binary
- Move this output to a bucket
- Register is in model registry against an image for execution (this does no change where it is stored)
- You can now call the model via endpoints sending your features and getting predictions back
- Model management is then managed via endpoints and registry

gs://my-ml-artifacts/models/churn/v1/model.pkl
gs://my-ml-artifacts/models/churn/v2/model.pkl
gs://my-ml-artifacts/models/llm-finetune/v3/
