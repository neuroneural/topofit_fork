The following three scripts are able to be run portably within a singularity container 
train.sh, evaluate.sh, and preprocess.sh. 
Focus was placed on maintaining evaluate.sh, however preprocess can be run if a Freesurfer installation is available to source (version 6 and 7 probably work).


In order to run evaluate.sh or train.sh gpu support is needed. An srun session similar to the following will suffice:
srun -p qTRDGPUH -A PSYC0002 -v -n1 -c 10 --mem=20G --gres=gpu:v100:1 --nodelist=trendsdgx003.rs.gsu.edu --pty /bin/bash

sometimes 003 node will be busy, you can replace 003 with 001,002,or 004. 
More cluster information can be found here:
https://trendscenter.github.io/wiki/docs/Cluster_queue_information.html#cluster-configuration

example srun commands can be found on the trends wiki
https://trendscenter.github.io/wiki/docs/SLURM_overview.html#example-commands
or you can find more information at slurm docs https://slurm.schedmd.com/srun.html

on a node that has singularity and the appropriate gpu support depending on the script (mentioned above), the following commands will run those scripts. 
First, you will need a copy of the appropriate topofit code/tag. Tag v1.0 was created in order to ensure that the code for this readme was stamped and available for
posterity. 

git clone -b v1.0 https://github.com/neuroneural/topofit.git

then cd topofit 

then run the following commands for each script:


singularity exec --nv --bind /data:/data/,/home:/home/,.:/topofit/ /data/users2/washbee/containers/topofitV1_release.sif /topofit/singularity_run/train.sh

singularity exec --nv --bind /data:/data/,/home:/home/,.:/topofit/ /data/users2/washbee/containers/topofitV1_release.sif /topofit/singularity_run/evaluate.sh

singularity exec --bind /data:/data/,/home:/home/,.:/topofit/ /data/users2/washbee/containers/topofitV1_release.sif /topofit/singularity_run/preprocess.sh

exec runs the .sh scripts at the end of the command, which are located at the --bind directory (/topofit/) /topofit/singularity_run/...
when using the bind command, the format is <hostdirectory>:<containerMountDirectory>, so the above command assumes you are running these commands from within the cloned singularity codebase 
you may bind more directories, seperated by commas. 

The --nv command enables nvidia gpu support. The --nv command is not necessary for preprocessing. 
It's possible the /home directory doesnt' need to be mounted. One may potentially remove that from the above command. 

Most importantly:
  each one of these shell scripts is examples of how to run the singularity container. Given the needs of whoever runs these containers will be quite unique, it is impossible
  to anticipate every possible usecase here. So, I have enabled the exceptional flexibility of using bash scripting with the exec command, but leave it to the end user 
  to update each script to suit their needs. it is conceivable that you could move the singularity exec ... command into the scrips so you don't need to type that.
  Or, you might want to add variables to each script so you can run more dynamically. 
  At minimum, you will need to change the paths inside the scripts to suit your data. 
  And, for the preprocess script it is likely advisable to enable variable support so you can use gnu parallel on a high performance cluster. 
  I will leave that for posterity to do. 
