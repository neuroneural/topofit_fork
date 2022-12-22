#!/bin/bash -p
. /opt/miniconda3/bin/activate topofit
#enter the command you would like to run below or modify this script to be more dynamic
#eg. /topofit/evaluate ...
#eg. /topofit/train ... 
#eg. /topofit/preprocess ...
#the following example requires --bind yourtopofitclone:/topofit/
. $FREESURFER_HOME/SetUpFreeSurfer.sh

readarray -t a < /topofit/singularity/subjs.txt
#echo ${a[0]}
read -a pmdata <<< "${a[$1]}"
echo "pmdata" $pmdata ${pmdata[0]}  

/topofit/preprocess /data/users2/washbee/speedrun/topofit-data/${pmdata[0]}

