import json
import os

#lta_base_directory = '/home/users/washbee1/tmp/ltafiles/'#end with / 
lta_base_directory = os.getcwd()+'/ltafiles/'
pairings = dict()

with open('train.txt','r') as trainpaths:
    for path in trainpaths.readlines():
        pairings['subj_base/'+path.strip()] = lta_base_directory+path.strip().split('/')[-1]+'.talairach.xfm.lta'
        print('subj_base/'+path.strip(),pairings['subj_base/'+path.strip()])

js = json.dumps(pairings, indent = 4)
print(js)
with open("train.json", "w") as outfile:
    json.dump(pairings, outfile, indent = 4)

pairings = dict()
with open('val.txt','r') as trainpaths:
    for path in trainpaths.readlines():
        pairings['subj_base/'+path.strip()] = lta_base_directory+path.strip().split('/')[-1]+'.talairach.xfm.lta'
        print('subj_base/'+path.strip(),pairings['subj_base/'+path.strip()])

js = json.dumps(pairings, indent = 4)
print(js)
with open("val.json", "w") as outfile:
    json.dump(pairings, outfile, indent = 4)
