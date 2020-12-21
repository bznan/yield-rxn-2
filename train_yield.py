#!/usr/bin/env python3

import argparse
import logging
import os
import torch
from torch.utils.data import DataLoader, random_split
import json
import rdkit.Chem as Chem
import rdkit
from rxntorch.containers.reaction import Rxn
from rxntorch.containers.molecule import Mol
from rxntorch.containers.dataset import RxnGraphDataset as RxnGD
from rxntorch.utils import collate_fn
from rxntorch.models.yield_network import YieldNet as RxnNet, YieldTrainer as RxnTrainer
import warnings
warnings.filterwarnings("ignore")
from rdkit.Chem import AllChem
from rdkit.Chem import Draw
from collections import defaultdict

from torch import randperm
from torch._utils import _accumulate
from torch.utils.data import Dataset,Subset
import sys


def utils_random_split(dataset, lengths,generator):
    r"""
    Randomly split a dataset into non-overlapping new datasets of given lengths.
    """
    # Cannot verify that dataset is Sized
    if sum(lengths) != len(dataset):  # type: ignore
        raise ValueError("Sum of input lengths does not equal the length of the input dataset!")

    indices = randperm(sum(lengths), generator=generator).tolist()
    return [Subset(dataset, indices[offset - length : offset]) for offset, length in zip(_accumulate(lengths), lengths)]


parser = argparse.ArgumentParser()

parser.add_argument("-p", "--dataset_path", type=str, default='./data/', help="train dataset")
parser.add_argument("-mp","--mol_path", type=str, default='doyle_reaction_mols', help="path to mol files")

parser.add_argument("-c", "--train_dataset", required=True, type=str, help="train dataset")
parser.add_argument("-t", "--test_dataset", type=str, default=None, help="test set")
parser.add_argument("-op", "--output_path", type=str, default='./output/', help="saved model path")
parser.add_argument("-o", "--output_name", required=True, type=str, help="e.g. rxntorch.model")
parser.add_argument("-ds", "--test_split", type=float, default=0.2, help="Ratio of samples to reserve for test data")

parser.add_argument("-b", "--batch_size", type=int, default=20, help="number of batch_size")
parser.add_argument("-tb", "--test_batch_size", type=int, default=None, help="batch size for evaluation")
parser.add_argument("-e", "--epochs", type=int, default=10, help="number of epochs")
parser.add_argument("-hs", "--hidden", type=int, default=300, help="hidden size of model layers")
parser.add_argument("-l", "--layers", type=int, default=3, help="number of layers")

parser.add_argument("--lr", type=float, default=1e-2, help="learning rate of the optimizer")
parser.add_argument("-lrd", "--lr_decay", type=float, default=0.9,
                    help="Decay factor for reducing the learning rate")
parser.add_argument("-lrs", "--lr_steps", type=int, default=10000,
                    help="Number of steps between learning rate decay")
parser.add_argument("--adam_weight_decay", type=float, default=0.0, help="weight_decay of adam")
parser.add_argument("--adam_beta1", type=float, default=0.9, help="adam first beta value")
parser.add_argument("--adam_beta2", type=float, default=0.999, help="adam second beta value")
parser.add_argument("-gc", "--grad_clip", type=float, default=None, help="value for gradient clipping")
parser.add_argument("-pw", "--pos_weight", type=float, default=None, help="Weights positive samples for imbalance")

parser.add_argument("-w", "--num_workers", type=int, default=4, help="dataloader worker size")
parser.add_argument("--with_cuda", type=bool, default=True, help="training with CUDA: true, or false")
parser.add_argument("--cuda_devices", type=int, nargs='*', default=None, help="CUDA device ids")

parser.add_argument("--log_freq", type=int, default=50, help="printing loss every n iter: setting n")
parser.add_argument("--seed", type=int, default=12, help="random seed")
parser.add_argument("-ud","--use_domain", type=str, required='True', help="use domain features or not")





args = parser.parse_args()
#torch.cuda.set_device(args.gpu)
torch.manual_seed(12)
torch.cuda.manual_seed_all(12)
if args.use_domain=='True':
    with_domain='w_domain'
elif args.use_domain=='only_domain':
    with_domain='o_domain'
else:
    with_domain='no_domain'

model_name = '-'.join(map(str,[args.output_name, with_domain, args.seed, args.hidden, args.layers, args.epochs, args.lr, args.lr_decay, args.lr_steps,args.batch_size]))
output_path=args.output_path + model_name +'/'



random_seed=args.seed
if not os.path.exists(output_path):
    os.mkdir(output_path)


#outputfile = os.path.join(args.output_path,model_name)

logfile = '.'.join((args.output_name, "log"))
logpath = os.path.join(output_path, logfile)
logging.basicConfig(level=logging.INFO, style='{', format="{asctime:s}: {message:s}",
                    datefmt="%m/%d/%y %H:%M:%S", handlers=(
                    logging.FileHandler(logpath), logging.StreamHandler()))

################################################################
#Build RxnGD and DataLoaders
################################################################
logging.info("{:-^80}".format("Dataset"))
#dataset = RxnGD(args.train_dataset, path=args.dataset_path)
dataset = RxnGD(args.train_dataset, mol_path=args.mol_path, path=args.dataset_path)
sample = dataset[3]

afeats_size, bfeats_size, binary_size, dmfeats_size = (sample["atom_feats"].shape[-1], sample["bond_feats"].shape[-1],
                                        sample["binary_feats"].shape[-1], sample['domain_feats'].shape[-1])
d1,d2,d3 = sample["binary_feats"].shape
binary_size= d3*d2


n_samples = len(dataset)
n_test = int(n_samples * args.test_split)
n_train = n_samples - n_test
logging.info("Splitting dataset into {:d} samples for training and {:d} samples for testing".format(
    n_train, n_test))
train_set, test_set = utils_random_split(dataset, (n_train, n_test),generator=torch.Generator().manual_seed(random_seed))

logging.info("{:-^80}".format("Data loaders"))
logging.info("Batch size: {:d}  Workers: {:d}  Shuffle per epoch: {}".format(args.batch_size, args.num_workers, True))
logging.info("Drop incomplete batches: {}".format(True))

train_dataloader = DataLoader(train_set, batch_size=args.batch_size, num_workers=args.num_workers, shuffle=True,
                              collate_fn=collate_fn, drop_last=True)

test_batch_size = args.test_batch_size if args.test_batch_size is not None else args.batch_size
test_dataloader = DataLoader(test_set, batch_size=test_batch_size, num_workers=args.num_workers, collate_fn=collate_fn)


logging.info("{:-^80}".format("Model"))
logging.info("Graph convolution layers: {}  Hidden size: {}".format(
    args.layers, args.hidden, args.batch_size, args.epochs))

################################################################
#Build RxnNet and RxnTrainer
################################################################

#torch.manual_seed(12)
net = RxnNet(depth=args.layers, afeats_size=afeats_size, bfeats_size=bfeats_size,
             hidden_size=args.hidden, binary_size=binary_size,dmfeats_size=dmfeats_size, use_domain=args.use_domain)
logging.info("Total Parameters: {:,d}".format(sum([p.nelement() for p in net.parameters()])))

logging.info("{:-^80}".format("Trainer"))
logging.info("Optimizer: {}  Beta1: {}  Beta2: {}".format("Adam", args.adam_beta1, args.adam_beta2))
logging.info("Learning rate: {}  Learning rate decay: {}  Steps between updates: {}".format(
    args.lr, args.lr_decay, args.lr_steps))
logging.info("Weight decay: {}  Gradient clipping: {}  Positive sample weighting: {}".format(
    args.adam_weight_decay, args.grad_clip, args.pos_weight))
trainer = RxnTrainer(net, lr=args.lr, betas=(args.adam_beta1, args.adam_beta2), weight_decay=args.adam_weight_decay,
                     with_cuda=args.with_cuda, cuda_devices=args.cuda_devices, log_freq=args.log_freq,
                     grad_clip=args.grad_clip, pos_weight=args.pos_weight, lr_decay=args.lr_decay,
                     lr_steps=args.lr_steps)

################################################################
#Train
################################################################

#f_true = open(output_path+'train_scores.txt', 'a')
#f_pred = open(output_path+'y_pred.txt', 'w')

train_r2 = open(output_path+'train_scores.txt', 'a')
test_r2 = open(output_path+'test_scores.txt', 'a')

train_l = open(output_path+'train_loss.txt', 'a')
test_l = open(output_path+'test_loss.txt', 'a')
for epoch in range(args.epochs):
    r2_train, train_loss= trainer.train_epoch(epoch, train_dataloader)
    #trainer.save(epoch, args.output_name, args.output_path)
    a2, b2, r2_test ,test_loss = trainer.test_epoch(epoch, test_dataloader)

    train_r2.write(str(float(r2_train))+',')
    test_r2.write(str(float(r2_test))+',')
    
    train_l.write(str(float(train_loss))+',')
    test_l.write(str(float(test_loss))+',')
              
train_r2.close()  
test_r2.close()
train_l.close()
test_l.close()
              
"""
a2,b2=[],[]

train_scores =[]
test_scores =[]
train_losses = []
test_losses = []


for epoch in range(args.epochs):
    r2_train, train_loss= trainer.train_epoch(epoch, train_dataloader)
    #trainer.save(epoch, args.output_name, args.output_path)
    a2, b2, r2_test ,test_loss = trainer.test_epoch(epoch, test_dataloader)
    train_scores.append(r2_train)
    test_scores.append(r2_test)
    train_losses.append(train_loss)
    test_losses.append(test_loss)
    
with open(output_path+'y_true.txt', 'w') as f_true, open(output_path+'y_pred.txt', 'w') as f_pred:
    f_true.write(','.join(map(str, [float(n[0]) for n in a2])))
    f_pred.write(','.join(map(str, [float(n[0]) for n in b2])))
    
with open(output_path+'train_scores.txt', 'w') as train_r2, open(output_path+'test_scores.txt', 'w') as test_r2:
    train_r2.write(','.join(map(str, [float(n) for n in train_scores])))
    test_r2.write(','.join(map(str, [float(n) for n in test_scores])))
    
with open(output_path+'train_loss.txt', 'w') as train_l, open(output_path+'test_loss.txt', 'w') as test_l:
    train_l.write(','.join(map(str, [float(n) for n in train_losses])))
    test_l.write(','.join(map(str, [float(n) for n in test_losses])))
"""
