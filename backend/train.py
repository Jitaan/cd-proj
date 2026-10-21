# train.py - builds a default model (C mode)
import os, pickle

# Default: recommend all passes
model = {
    "fold": 1, "alg": 1, "cse": 1, "cfg": 1, "dce": 1,
    "copy_prop": 1, "dag": 1,
    "licm": 1, "strength_red": 1, "iv_elim": 1, "loop_unroll": 1, "loop_fuse": 1,
    "rename": 1, "machine_idiom": 1,
    "features": ["n_instr", "n_const_binops", "n_const_copies", "n_repeated_exprs",
                 "n_dead_defs", "n_blocks", "n_loops", "copy_ratio",
                 "n_alg_sites", "n_const_branches", "n_peephole_sites"]
}
with open(os.path.join(os.path.dirname(__file__), "model.pkl"), "wb") as f:
    pickle.dump(model, f)
print("saved default model.pkl")
