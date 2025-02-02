import learnedcardinalities.train
import torch
import random
import numpy as np

# disable randomness
torch.manual_seed(2023)
random.seed(2023)
np.random.seed(2023)
torch.use_deterministic_algorithms(True)

# hard-coded parameters
queries = 1500
epochs = 200
batch = 1024
hid = 256
cuda = False

# model details
name2details = {}
# dicts = None
# min_val = None
# max_val = None
# model = None

# default info
default_column_min_max_vals = {
    "join": {
        "ss.ss_item_sk": [1.0, 18000.0],
        "ss.ss_store_sk": [1.0, 10.0],
        "sr.sr_item_sk": [1.0, 18000.0],
        "sr.sr_store_sk": [1.0, 10.0],
    }
}
default_predicate_templates = {}


def retrain(model_name, tables, joins, training_set):
    global name2details
    if model_name not in name2details:
        name2details[model_name] = (None, None, None, None)
    name2details[model_name] = learnedcardinalities.train.run(
        training_set,
        tables,
        joins,
        default_column_min_max_vals[model_name],
        default_predicate_templates[model_name],
        queries,
        epochs,
        batch,
        hid,
        cuda,
    )


def predict_one(model_name, bounds, table_template, join_template):
    global name2details
    assert model_name in name2details
    dicts, min_val, max_val, model = name2details[model_name]
    return learnedcardinalities.train.predict_one(
        bounds,
        table_template,
        join_template,
        dicts,
        min_val,
        max_val,
        default_column_min_max_vals[model_name],
        default_predicate_templates[model_name],
        batch,
        model,
        cuda,
    )
