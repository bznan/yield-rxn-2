from __future__ import print_function

import torch
from torch.nn.utils.rnn import pad_sequence


def collate_fn(batch_data):
    """
    Takes a batch of data for the graph network model and collates it into
    torch tensors which are padded to accommodate different numbers of atoms
    """
    output = {}
    for key in batch_data[0].keys():
        if key == "binary_feats":
            to_stack = [sample[key] for sample in batch_data]
            n_atoms = [label.shape[0] for label in to_stack]
            max_atoms = max(n_atoms)
            #print("max_atoms: ",max_atoms)
            values = torch.zeros((len(to_stack), max_atoms, max_atoms, to_stack[0].shape[-1]))
            for i, (label, n_atom) in enumerate(zip(to_stack, n_atoms)):
                values[i,:n_atom,:n_atom] = label
            #print(key)
            #print("values: ",values.shape)        
        elif key == "n_atoms":
            values = torch.tensor([sample[key] for sample in batch_data], dtype=torch.int32)
        #elif key == "bond_labels":
        #    values = torch.cat([sample[key] for sample in batch_data], dim=0)
        elif key == "yield_label":
            values = torch.cat([torch.tensor(sample[key].unsqueeze(1), dtype=torch.float) for sample in batch_data], dim=0)
            #values = pad_sequence([sample[key].unsqueeze(1) for sample in batch_data],batch_first=True)
            #values = values
        elif key == "sparse_idx":
            n_pairs = [sample[key].shape[0] for sample in batch_data]
            batch_idxs = [torch.full((n_pairs[i],1), i, dtype=torch.int64) for i in range(len(n_pairs))]
            values = torch.cat([torch.cat([batch_idx, sample[key]], dim=1) for (
                batch_idx, sample) in zip(batch_idxs, batch_data)], dim=0)

        else:
            values = pad_sequence([sample[key] for sample in batch_data], batch_first=True)
            #print(key)
            #print("values: ",values.shape)
        output[key] = values
    return output

