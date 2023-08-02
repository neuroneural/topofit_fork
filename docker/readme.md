# How to build with docker then singularity
The workflow I'm currently aware of at trends requires us to build with a Dockerfile using docker then build the image into a singularity container sif file.
This is to secure the cluster and isolate the elevated privileges required of docker. Singularity when not run with sudo does not successfully allow for building locally from a recipe.
As a result, the following is our workflow
## building with docker
    docker build -t yourname/yourproject .

run the above command within the same directory as the Dockerfile and environment.yml file. 
## building with singularity
then, one should build the image into a sif file using the following command:

    singularity build topofit.sif docker-daemon://yourname/yourproject:latest

## Anticipated changes to the above workflow
It is likely in the future remote builds will be encouraged instead of building with docker. Remote builds didn't have the ability to use the copy command,
which is why I shuned its use. There is a very real danger if you don't use version numbers of libraries you will run into broke builds later using the same script. 
I avoided this with yml.

# Why yml
The yml file allows me to export the conda environment and recreate exactly the dependency tree using very few commands

## export yml 
From within the appropriate environment run 

    conda env export > environment.yml

This is unneccessary for you to do. This is just useful information for posterity. 

## About broken dependies in the original yml
  not every whl or pip file worked correctly. One I needed to remove from the yml file and install with pip commands (torch-scatter) .
  
