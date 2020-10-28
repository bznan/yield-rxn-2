import torch
import torch.nn as nn
import torch.nn.functional as F
from .layers import Linear


class YieldScoring(nn.Module):
    def __init__(self, hidden_size, binary_size):
        super(YieldScoring, self).__init__()
        #self.fclocal = Linear(hidden_size, hidden_size, bias=False)
        self.fcglobal = Linear(hidden_size, hidden_size)
        #self.fcbinary = Linear(binary_size, hidden_size, bias=False)
        self.fcscore = Linear(hidden_size, 1)

    #def forward(self, local_pair, global_pair, binary, sparse_idx):
    def forward(self, local_features, global_features, binary, sparse_idx):
        #binary_feats = binary[sparse_idx[:,0],sparse_idx[:,1],sparse_idx[:,2]]
        #pair_feats = F.relu(self.fclocal(local_pair) + self.fcglobal(global_pair))# + self.fcbinary(binary_feats))
        #features= F.relu(self.fcglobal(local_pair)+self.fcglobal(global_pair))# + self.fcbinary(binary_feats))
        #print("local features before relu",local_features.shape)
        features= F.relu(self.fcglobal( local_features)+self.fcglobal(global_features))# + self.fcbinary(binary_feats))
        #features= F.relu(self.fcglobal( local_features))#+self.fcglobal(global_features))# + self.fcbinary(binary_feats))
        #score = self.fcscore(pair_feats)
        #print("local features after relu",features.shape)
        score = self.fcscore(features)
        final_score=torch.mean(torch.abs(score),dim=1)
        #print("score",score.shape)
        return final_score



