from fastapi import FastAPI
import joblib

app = FastAPI()

model = joblib.load("/model/model.pkl")

@app.post("/predict")
def predict(request: dict):
    features = request["instances"]
    preds = model.predict(features)
    return {"predictions": preds.tolist()}
