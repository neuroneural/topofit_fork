#!/bin/bash
#SBATCH -n 1
#SBATCH -c 10
#SBATCH --mem=30g
#SBATCH -p qTRDGPUH
#SBATCH --gres=gpu:v100:1
#SBATCH --nodelist=trendsdgx003.rs.gsu.edu 
#SBATCH -t 3-00:00
#SBATCH -J topofitl
#SBATCH -e /data/users2/washbee/topofit/jobs/error%A.err
#SBATCH -o /data/users2/washbee/topofit/jobs/out%A.out
#SBATCH -A PSYC0002
#SBATCH --mail-type=ALL
#SBATCH --mail-user=washbee1@student.gsu.edu
#SBATCH --oversubscribe

sleep 5s


singularity exec --nv --bind /data:/data/,/home:/home/,$HOME/projects/topofit:/topofit/,/data/users2/washbee/hcp-plis-subj/:/subj /data/users2/washbee/containers/topofitV1_release.sif /topofit/singularity_run/train.sh lh &

wait

sleep 10s
