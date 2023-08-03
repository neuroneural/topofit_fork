#!/bin/bash -p
. /opt/miniconda3/bin/activate topofit
#enter the command you would like to run below or modify this script to be more dynamic
#eg. /topofit/evaluate ...
#eg. /topofit/train ... 
#eg. /topofit/preprocess ...
#the following example requires --bind yourtopofitclone:/topofit/
readarray -t a < /topofit/singularity/test_ids.csv
echo 'array is read'
/topofit/evaluate --subjs /data/users2/washbee/speedrun/topofit-data-surfatest/${a[${SLURM_ARRAY_TASK_ID}]} --hemi lh --model /data/users2/washbee/speedrun/topofit/output/lh.2125.pt
