import os
import io
from glob import glob
from collections import OrderedDict, defaultdict

import numpy as np
import torch
import torch.distributed as dist
import math
import PIL.Image
from mpi4py import MPI


# Note! This is l2 square, not l2
def l2(a, b):
    return torch.pow(torch.abs(a - b), 2).sum(dim=1)


# required when we load optimizer from a checkpoint
def optimizer_cuda(optimizer, device):
    for state in optimizer.state.values():
        for k, v in state.items():
            if isinstance(v, torch.Tensor):
                state[k] = v.to(device)


def get_ckpt_path(base_dir, ckpt_num):
    if ckpt_num is None:
        return get_recent_ckpt_path(base_dir)
    files = glob(os.path.join(base_dir, "*.pt"))
    for f in files:
        if "ckpt_%08d.pt" % ckpt_num in f:
            return f, ckpt_num
    raise Exception("Did not find ckpt_%s.pt" % ckpt_num)


def get_recent_ckpt_path(base_dir):
    files = glob(os.path.join(base_dir, "*.pt"))
    files.sort()
    if len(files) == 0:
        return None, None
    max_step = max([f.rsplit("_", 1)[-1].split(".")[0] for f in files])
    paths = [f for f in files if max_step in f]
    if len(paths) == 1:
        return paths[0], int(max_step)
    else:
        raise Exception("Multiple most recent ckpts %s" % paths)


def save_distribution_imgs(grid_arr, blended_arr, grid_img_path: str='grid.jpg', blended_img_path: str='blended.jpg', nrow: int=8, padding: int=2, pad_value: int=0):
    '''
    grid_arr: a 4 dimensional (n_img, channel, height, width) np array of images
    blended_arr: a 3 dimensional (channel, height, width) np array of one blended image
    '''
    grid_tensor = torch.from_numpy(grid_arr)
    # make the mini-batch of images into a grid
    nmaps = grid_tensor.size(0)
    xmaps = min(nrow, nmaps)
    ymaps = int(math.ceil(float(nmaps) / xmaps))
    height, width = int(grid_tensor.size(2) + padding), int(grid_tensor.size(3) + padding)
    num_channels = grid_tensor.size(1)
    grid = grid_tensor.new_full((num_channels, height * ymaps + padding, width * xmaps + padding), pad_value)
    k = 0
    for y in range(ymaps):
        for x in range(xmaps):
            if k >= nmaps:
                break
            grid.narrow(1, y * height + padding, height - padding)\
                .narrow(2, x * width + padding, width - padding)\
                .copy_(grid_tensor[k])
            k = k + 1

    grid_img = (grid.numpy() * 255).astype('uint8')
    grid_img = np.transpose(grid_img, (1,2,0))
    PIL.Image.fromarray(grid_img).save(grid_img_path)
    blended_img = (blended_arr * 255).astype('uint8')
    blended_img = np.transpose(blended_img, (1,2,0))
    PIL.Image.fromarray(blended_img).save(blended_img_path)


def numpy_to_img(arr, name):
    img = (arr * 255).astype('uint8')
    img = np.transpose(img, (1,2,0))
    PIL.Image.fromarray(img).save(name + '.jpg')


def count_parameters(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


def slice_tensor(input, indices):
    ret = {}
    for k, v in input.items():
        ret[k] = v[indices]
    return ret


def average_gradients(model):
    size = float(dist.get_world_size())
    for p in model.parameters():
        if p.grad is not None:
            dist.all_reduce(p.grad.data, op=dist.ReduceOp.SUM)
            p.grad.data /= size


def ensure_shared_grads(model, shared_model):
    """for A3C"""
    for param, shared_param in zip(model.parameters(), shared_model.parameters()):
        if shared_param.grad is not None:
            return
        shared_param._grad = param.grad


def compute_gradient_norm(model):
    grad_norm = 0
    for p in model.parameters():
        if p.grad is not None:
            grad_norm += (p.grad.data ** 2).sum().item()
    return grad_norm


def compute_weight_norm(model):
    weight_norm = 0
    for p in model.parameters():
        if p.data is not None:
            weight_norm += (p.data ** 2).sum().item()
    return weight_norm


def compute_weight_sum(model):
    weight_sum = 0
    for p in model.parameters():
        if p.data is not None:
            weight_sum += p.data.abs().sum().item()
    return weight_sum


# sync_networks across the different cores
def sync_networks(network):
    """
    netowrk is the network you want to sync
    """
    comm = MPI.COMM_WORLD
    flat_params, params_shape = _get_flat_params(network)
    comm.Bcast(flat_params, root=0)
    # set the flat params back to the network
    _set_flat_params(network, params_shape, flat_params)


# get the flat params from the network
def _get_flat_params(network):
    param_shape = {}
    flat_params = None
    for key_name, value in network.named_parameters():
        param_shape[key_name] = value.cpu().detach().numpy().shape
        if flat_params is None:
            flat_params = value.cpu().detach().numpy().flatten()
        else:
            flat_params = np.append(flat_params, value.cpu().detach().numpy().flatten())
    return flat_params, param_shape


# set the params from the network
def _set_flat_params(network, params_shape, params):
    pointer = 0
    if hasattr(network, "_config"):
        device = network._config.device
    else:
        device = torch.device("cpu")

    for key_name, values in network.named_parameters():
        # get the length of the parameters
        len_param = np.prod(params_shape[key_name])
        copy_params = params[pointer : pointer + len_param].reshape(
            params_shape[key_name]
        )
        copy_params = torch.tensor(copy_params).to(device)
        # copy the params
        values.data.copy_(copy_params.data)
        # update the pointer
        pointer += len_param


# sync gradients across the different cores
def sync_grads(network):
    flat_grads, grads_shape = _get_flat_grads(network)
    comm = MPI.COMM_WORLD
    global_grads = np.zeros_like(flat_grads)
    comm.Allreduce(flat_grads, global_grads, op=MPI.SUM)
    _set_flat_grads(network, grads_shape, global_grads)


def _set_flat_grads(network, grads_shape, flat_grads):
    pointer = 0
    if hasattr(network, "_config"):
        device = network._config.device
    else:
        device = torch.device("cpu")

    for key_name, value in network.named_parameters():
        if key_name in grads_shape:
            len_grads = np.prod(grads_shape[key_name])
            copy_grads = flat_grads[pointer : pointer + len_grads].reshape(
                grads_shape[key_name]
            )
            copy_grads = torch.tensor(copy_grads).to(device)
            # copy the grads
            value.grad.data.copy_(copy_grads.data)
            pointer += len_grads


def _get_flat_grads(network):
    grads_shape = {}
    flat_grads = None
    for key_name, value in network.named_parameters():
        try:
            grads_shape[key_name] = value.grad.data.cpu().numpy().shape
        except:
            print("Cannot get grad of tensor {}".format(key_name))
            continue

        if flat_grads is None:
            flat_grads = value.grad.data.cpu().numpy().flatten()
        else:
            flat_grads = np.append(flat_grads, value.grad.data.cpu().numpy().flatten())
    return flat_grads, grads_shape


def PIL_to_tensor(pic):
    # Convert a ``PIL Image`` to tensor.
    if not(_is_pil_image(pic)):
        raise TypeError('pic should be PIL Image or ndarray. Got {}'.format(type(pic)))

    # handle PIL Image
    if pic.mode == 'I':
        img = torch.from_numpy(np.array(pic, np.int32, copy=False))
    elif pic.mode == 'I;16':
        img = torch.from_numpy(np.array(pic, np.int16, copy=False))
    elif pic.mode == 'F':
        img = torch.from_numpy(np.array(pic, np.float32, copy=False))
    elif pic.mode == '1':
        img = 255 * torch.from_numpy(np.array(pic, np.uint8, copy=False))
    else:
        img = torch.ByteTensor(torch.ByteStorage.from_buffer(pic.tobytes()))

    img = img.view(pic.size[1], pic.size[0], len(pic.getbands()))
    # put it from HWC to CHW format
    img = img.permute((2, 0, 1)).contiguous()
    if isinstance(img, torch.ByteTensor):
        return img.float().div(255)
    else:
        return img

def fig2tensor(draw_func):
    def decorate(*args, **kwargs):
        tmp = io.BytesIO()
        fig = draw_func(*args, **kwargs)
        fig.savefig(tmp, dpi=88)
        tmp.seek(0)
        fig.clf()
        return PIL_to_tensor(PIL.Image.open(tmp))

    return decorate


def tensor2np(t):
    if isinstance(t, torch.Tensor):
        return t.clone().detach().cpu().numpy()
    else:
        return t


def tensor2img(tensor):
    if len(tensor.shape) == 4:
        assert tensor.shape[0] == 1
        tensor = tensor.squeeze(0)
    img = tensor.permute(1, 2, 0).detach().cpu().numpy()
    import cv2

    cv2.imwrite("tensor.png", img)


def obs2tensor(obs, device):
    if isinstance(obs, list):
        obs = list2dict(obs)

    return OrderedDict(
        [
            (k, torch.tensor(np.stack(v), dtype=torch.float32).to(device))
            for k, v in obs.items()
        ]
    )


# transfer a numpy array into a tensor
def to_tensor(x, device):
    if isinstance(x, dict):
        return OrderedDict(
            [(k, torch.tensor(v, dtype=torch.float32).to(device)) for k, v in x.items()]
        )
    if isinstance(x, list):
        return [torch.tensor(v, dtype=torch.float32).to(device) for v in x]
    return torch.tensor(x, dtype=torch.float32).to(device)


def list2dict(rollout):
    ret = OrderedDict()
    for k in rollout[0].keys():
        ret[k] = []
    for transition in rollout:
        for k, v in transition.items():
            ret[k].append(v)
    return ret


# From softlearning repo
def flatten(unflattened, parent_key="", separator="/"):
    items = []
    for k, v in unflattened.items():
        if separator in k:
            raise ValueError("Found separator ({}) from key ({})".format(separator, k))
        new_key = parent_key + separator + k if parent_key else k
        if isinstance(v, collections.MutableMapping) and v:
            items.extend(flatten(v, new_key, separator=separator).items())
        else:
            items.append((new_key, v))

    return OrderedDict(items)


# From softlearning repo
def unflatten(flattened, separator="."):
    result = {}
    for key, value in flattened.items():
        parts = key.split(separator)
        d = result
        for part in parts[:-1]:
            if part not in d:
                d[part] = {}
            d = d[part]
        d[parts[-1]] = value

    return result


# from https://github.com/MishaLaskin/rad/blob/master/utils.py
def center_crop(img, out=84):
    """
        args:
        imgs: np.array shape (H,W,C) or (N,H,W,C)
        out: output size (e.g. 84)
        returns np.array shape (1,C,H,W) or (1,N*C,H,W)
    """
    if len(img.shape) == 3:
        img = img.transpose(2, 0, 1)
    elif len(img.shape) == 4:
        img = img.transpose(0, 3, 1, 2).reshape(-1, img.shape[1], img.shape[2])

    h, w = img.shape[1:]
    new_h, new_w = out, out

    top = (h - new_h) // 2
    left = (w - new_w) // 2

    img = img[:, top : top + new_h, left : left + new_w]
    img = np.expand_dims(img, axis=0)
    return img


# from https://github.com/MishaLaskin/rad/blob/master/data_augs.py
def random_crop(imgs, out=84):
    """
        args:
        imgs: np.array shape (B,H,W,C) or (B,N,H,W,C)
        out: output size (e.g. 84)
        returns np.array shape (B,C,H,W) or (B,N*C,H,W)
    """
    if len(imgs.shape) == 4:
        imgs = imgs.transpose(0, 3, 1, 2)
    elif len(imgs.shape) == 5:
        imgs = imgs.transpose(0, 1, 4, 2, 3).reshape(
            imgs.shape[0], -1, imgs.shape[2], imgs.shape[3]
        )

    b, c, h, w = imgs.shape
    crop_max = h - out + 1
    w1 = np.random.randint(0, crop_max, b)
    h1 = np.random.randint(0, crop_max, b)
    cropped = np.empty((b, c, out, out), dtype=imgs.dtype)
    for i, (img, w11, h11) in enumerate(zip(imgs, w1, h1)):
        cropped[i] = img[:, h11 : h11 + out, w11 : w11 + out]
    return cropped
