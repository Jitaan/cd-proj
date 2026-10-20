# train.py - builds a default model (C mode)
import os, pickle

# Default: recommend all passes
model = {"fold": 1, "alg": 1, "cse": 1, "cfg": 1, "dce": 1,
         "features": ["n_instr"]}
with open(os.path.join(os.path.dirname(__file__), "model.pkl"), "wb") as f:
    pickle.dump(model, f)
print("saved default model.pkl")
