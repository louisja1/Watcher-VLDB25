# Watcher-VLDB25
the github repository of Watcher for VLDB 2025 reviewer only

## Python Package Requirement
```
torch=2.1.0+cu121
tqdm==4.66.4
numpy==1.26.4
psycopg2==2.9.9 (dt dec pq3 ext lo64)
plyvel==1.5.1
```

## Path setup
There are some paths to manually setup for connecting PostgreSQL and LevelDB in `pg_hint_utility.py`, `connection.py`, `db_wrapper.py`

## Example Usages For Running Q013a of six-batch setting
```
sh run.sh
```

Inside `run.sh`:
```
echo "2 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 base_main1d.py ../input_configs/dsb_sf2_no-retrain_no-cache_config_Q013a-6B.json # for running Baseline
echo "3 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 truecard_main1d.py ../input_configs/dsb_sf2_true-card_config_Q013a-6B.json # for running True
echo "4 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 twotier_main1d.py ../input_configs/dsb_sf2_twotier_config_Q013a-6B_correctjoin2_trial1.json # for running SWatcher+
echo "6 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 baseline1d.py ../input_configs/dsb_sf2_baseline_config_Q013a-6B_rt12.json # for running Periodic
echo "5 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 main1d.py ../input_configs/dsb_sf2_config_Q013a-6B.json # for running Watcher1D
```

Please also see the details in the json files in `input_configs/`

`data/` is large and zipped.