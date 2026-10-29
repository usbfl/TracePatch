from pathlib import Path
import pytest
from tracepatch.data import build_dataset
from tracepatch.common import read_json
from tracepatch.experiment import load_config, run_one


@pytest.fixture
def dataset(tmp_path):
    cfg=load_config(Path(__file__).resolve().parents[1]/"configs"/"smoke.yaml")
    cfg.update(dev_scenarios=1,test_scenarios=1,nodes=[24,24],deltas=[0,.25,.5,.75])
    root=tmp_path/"data"; manifest=build_dataset(cfg,root,demo=True)
    return root,manifest,cfg


@pytest.fixture
def episode(dataset):
    root,manifest,cfg=dataset
    item=manifest["entries"][0]
    return read_json(root/item["public"]),root/item["environment"],read_json(root/"evaluation"/(item["base_id"]+".json")),cfg


@pytest.fixture
def execute_episode(episode,tmp_path):
    public,env,gold,cfg=episode
    counter=[0]
    def execute(method="tracepatch",budget=128,**kw):
        counter[0]+=1
        return run_one(public,env,method,budget,cfg,tmp_path/(str(counter[0])+".sqlite"),**kw)
    return execute
