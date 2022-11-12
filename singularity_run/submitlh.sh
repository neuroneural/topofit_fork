#!/bin/bash
#SBATCH -n 1
#SBATCH -c 4
#SBATCH --mem=30g
#SBATCH -p qTRDGPUH
#SBATCH --gres=gpu:V100:1
#SBATCH -t 3-00:00
#SBATCH -J topofitl
#SBATCH -e /data/users2/washbee/topofit/jobs/error%A.err
#SBATCH -o /data/users2/washbee/topofit/jobs/out%A.out
#SBATCH -A psy53c17
#SBATCH --mail-type=ALL
#SBATCH --mail-user=washbee1@student.gsu.edu
#SBATCH --oversubscribe
#SBATCH --exclude=arctrdgn002


sleep 5s

module load singularity/3.10.2
singularity exec --nv --bind /data:/data/,/home:/home/,$HOME/projects/topofit:/topofit/,/data/users2/washbee/hcp-plis-subj/:/subj /data/users2/washbee/containers/speedrun/topofit_sr.sif /topofit/singularity_run/train.sh lh &

wait

sleep 10s
