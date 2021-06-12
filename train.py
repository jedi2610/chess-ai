import torch
import numpy as np

from torch import nn
from torch import optim
from tqdm import trange
from torchsummary import summary
from matplotlib import pyplot as plt
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset
from torch.utils.tensorboard import SummaryWriter

DATA_DIR = '/mnt/Seagate/Code/chess-ai/data'

# https://web.stanford.edu/~surag/posts/alphazero.html
# https://int8.io/monte-carlo-tree-search-beginners-guide/
# https://www.datahubbs.com/two-headed-a2c-network-in-pytorch/
# https://jeffbradberry.com/posts/2015/09/intro-to-monte-carlo-tree-search/
# https://nikcheerla.github.io/deeplearningschool/2018/01/01/AlphaZero-Explained/
# https://github.com/DylanSnyder31/AlphaZero-Chess/blob/660f50f56dc8772cceaf46d33a97aed8b0775fa8/Reinforcement_Learning/Monte_Carlo_Search_Tree/MCTS_main.py

class ChessDataset(Dataset):

    def __init__(self, data_dir):
        data = np.load(data_dir + '/processed_data.npz')
        self.x, self.policy, self.value = data['arr_0'], data['arr_1'], data['arr_2']

    def __len__(self):
        return len(self.x)

    def __getitem__(self, idx):
        return self.x[idx], self.policy[idx], self.value[idx]


class FCView(nn.Module):
    def __init__(self):
        super(FCView, self).__init__()

    def forward(self, x):
        shape = x.data.size(0)
        x = x.view(shape, -1)
        return x


class ConvBlock(nn.Module):

    def __init__(self, in_channels, out_channels, kernel_size, padding=0, stride=1):
        super(ConvBlock, self).__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, padding=padding, stride=stride)
        self.batch_norm = nn.BatchNorm2d(out_channels)

    def forward(self, x):
        x = F.relu(self.conv(x.float()))
        return self.batch_norm(x)


class OutBlock(nn.Module):

    def __init__(self):
        super(OutBlock, self).__init__()
        self.reshape = FCView()
        # (8 - 1 / 1) + 1
        self.conv_block_policy = ConvBlock(256, 2, 1)
        self.fc_policy = nn.Linear(2 * 8 * 8, 64)

        # (8 - 3 + 2 / 1) + 1
        self.conv_block_value = ConvBlock(256, 2, 3, 1, 1)
        self.fc1_value = nn.Linear(2 * 8 * 8, 64)
        self.fc2_value = nn.Linear(64, 1)

    def forward(self, x):
        policy = self.reshape(self.conv_block_policy(x))
        policy = self.fc_policy(policy)
        
        value = self.reshape(self.conv_block_value(x))
        value = F.relu(self.fc1_value(value))
        value = self.fc2_value(value)
        return F.softmax(policy, dim=1), torch.tanh(value).view(-1)


class Loss(nn.Module):
    def __init__(self):
        super(Loss, self).__init__()

    def forward(self, policy_pred, policy, value_pred, value):
        policy_loss = F.nll_loss(torch.log(policy_pred), policy.long())
        value_loss = F.mse_loss(value_pred, value)
        return policy_loss, value_loss


class Net(nn.Module):
    # ((img_size - kern_size + (2 * padding_size))/stride) + 1
    def __init__(self):
        super(Net, self).__init__()
        setattr(self, "conv-block-1", ConvBlock(6, 256, 3, 1, 1))
        for block in range(2, 11):
            # (8 - 3 + 2) / 1 + 1
            setattr(self, "conv-block-{}".format(block), ConvBlock(256, 256, 3, 1, 1))
        self.out_block = OutBlock()

    def forward(self, x):
        for block in range(1, 11):
            x = getattr(self, "conv-block-{}".format(block))(x)
        policy, value = self.out_block(x)
        return policy, value


if __name__ == '__main__':

    chess_dataset = ChessDataset(DATA_DIR)
    data_loader = DataLoader(chess_dataset, batch_size=64, shuffle=True, num_workers=6, drop_last=True)

    net = Net()
    opt = optim.Adam(net.parameters())
    loss = Loss()
    summary(net, input_size=(6, 8, 8))
    writer = SummaryWriter()

    EPOCHS = 10
    step = 0
    for epoch in trange(EPOCHS):
        for data, policy, value in data_loader:
            opt.zero_grad()
            policy_pred, value_pred = net(data)

            policy_loss, value_loss = loss(policy_pred, policy, value_pred, value)
            policy_loss.backward(retain_graph=True)
            value_loss.backward()
            writer.add_scalar("Policy Loss/train", policy_loss, step)
            writer.add_scalar("Value Loss/train", value_loss, step)
            opt.step()
            step += 1
            # t.set_description('policy loss %.2f value loss %.2f' % (policy_loss, value_loss))
        writer.flush()
    writer.close()
