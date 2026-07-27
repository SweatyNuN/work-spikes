import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import joblib

# 1. Load some example data
# Replace this with your own CSV later
df = pd.read_csv("data.csv")

# Assume the target column is named "label"
X = df.drop("label", axis=1)
y = df["label"]

# 2. Train/test split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# 3. Train a simple model
model = RandomForestClassifier(n_estimators=100)
model.fit(X_train, y_train)

# 4. Evaluate
preds = model.predict(X_test)
print("Accuracy:", accuracy_score(y_test, preds))

# 5. Save model artifact
joblib.dump(model, "model.pkl")
print("Saved model.pkl")
