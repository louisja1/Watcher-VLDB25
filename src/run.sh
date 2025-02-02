echo "2 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 base_main1d.py ../input_configs/dsb_sf2_no-retrain_no-cache_config_Q013a-6B.json
echo "3 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 truecard_main1d.py ../input_configs/dsb_sf2_true-card_config_Q013a-6B.json
echo "4 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 twotier_main1d.py ../input_configs/dsb_sf2_twotier_config_Q013a-6B_correctjoin2_trial1.json
echo "6 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 baseline1d.py ../input_configs/dsb_sf2_baseline_config_Q013a-6B_rt12.json
echo "5 ---------"
dropdb -p 5555 watcherdb
createdb -p 5555 -U yl762 watcherdb
python3 main1d.py ../input_configs/dsb_sf2_config_Q013a-6B.json