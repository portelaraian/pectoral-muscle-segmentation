import numpy as np
import torch
from torch import nn
from torch.optim import lr_scheduler
import monai
from monai.transforms import (
    AddChanneld,
    AsDiscreted,
    CastToTyped,
    LoadImaged,
    Orientationd,
    RandAffined,
    RandCropByPosNegLabeld,
    RandFlipd,
    RandGaussianNoised,
    ScaleIntensityRanged,
    Spacingd,
    SpatialPadd,
    ToTensord,
    ScaleIntensityd,
)
from utils.lr_schedulers import DiceCELoss


def _get_xforms(mode="train", keys=("image", "label")):
    """returns a composed transform."""

    xforms = [
        LoadImaged(keys),
        AddChanneld(keys),
        Orientationd(keys, axcodes="LPS"),
        Spacingd(keys, pixdim=(1.25, 1.25, 5.0), mode=(
            "bilinear", "nearest")[: len(keys)]),
        ScaleIntensityd(keys, minv=0.0, maxv=1.0),
        # ScaleIntensityRanged(keys[0], a_min=-1000.0, a_max=500.0, b_min=0.0, b_max=1.0, clip=True),
    ]

    if mode == "train":
        xforms.extend(
            [
                SpatialPadd(keys, spatial_size=(192, 192, -1),
                            mode="reflect"),  # ensure at least 192x192
                RandAffined(
                    keys,
                    prob=0.25,
                    # 3 parameters control the transform on 3 dimensions
                    rotate_range=(0.1, 0.1, None),
                    scale_range=(0.2, 0.2, None),
                    mode=("bilinear", "nearest"),
                    as_tensor_output=False,
                ),
                RandCropByPosNegLabeld(keys, label_key=keys[1],
                                       spatial_size=(192, 192, 16),
                                       num_samples=3),
                RandGaussianNoised(keys[0], prob=0.15, std=0.01),
                RandFlipd(keys, spatial_axis=0, prob=0.5),
                RandFlipd(keys, spatial_axis=1, prob=0.5),
                RandFlipd(keys, spatial_axis=2, prob=0.5),
            ]
        )

        dtype = (np.float32, np.uint8)

    if mode == "val":
        dtype = (np.float32, np.uint8)
    if mode == "infer":
        dtype = (np.float32,)

    xforms.extend([CastToTyped(keys, dtype=dtype), ToTensord(keys)])

    return monai.transforms.Compose(xforms)


def get_model(cfg):
    """returns a unet model instance."""

    n_classes = 2
    '''net = monai.networks.nets.BasicUNet(
        dimensions=3,
        in_channels=1,
        out_channels=n_classes,
        features=(32, 32, 64, 128, 256, 32),
        dropout=0.2,
    )'''

    '''
    net = monai.networks.nets.UNet(
        dimensions=3,
        in_channels=1,
        out_channels=n_classes, # 2
        channels=(16, 32, 64, 128, 256),
        strides=(2, 2, 2, 2),
        num_res_units=2,
        norm=Norm.BATCH,
    )
    '''

    net = monai.networks.nets.SegResNet(
        spatial_dims=3,
        init_filters=8,
        in_channels=1,
        out_channels=n_classes,
        dropout_prob=None,
        norm_name='group',
        num_groups=8,
        use_conv_final=True,
        blocks_down=(1, 2, 2, 4),
        blocks_up=(1, 1, 1),
    )

    return net


def get_loss(cfg):
    if cfg.loss.name == "DiceCELoss":
        return DiceCELoss()

    try:
        return getattr(monai.losses, cfg.loss.name)(**cfg.loss.params)
    except:
        print(
            f"Failed to import and load the loss function. Loss Function {cfg.loss.name}")


def get_optimizer(cfg, parameters):
    optimizer = getattr(torch.optim, cfg.optimizer.name)(
        parameters, **cfg.optimizer.params)

    log(f'optim: {cfg.optimizer.name}')

    return optimizer


def get_scheduler(cfg, optimizer):
    try:
        return getattr(lr_scheduler, cfg.scheduler.name)(
            optimizer, **cfg.scheduler.params)
    except:
        print(f"Failed to load the scheduler. Scheduler: {cfg.scheduler.name}")


def get_dataloader(cfg, mode, keys, data):
    if mode == 'train':
        train_transforms = _get_xforms("train", keys)
        dataset = monai.data.CacheDataset(
            data=data,
            transform=train_transforms
        )
    elif mode == 'val':
        val_transforms = factory.get_xforms("val", keys)
        dataset = monai.data.CacheDataset(
            data=data,
            transform=val_transforms
        )
    else:
        # Test
        pass

    return monai.data.DataLoader(
        dataset,
        batch_size=cfg.batch_size,
        shuffle=cfg.shuffle,
        num_workers=cfg.num_workers,
        pin_memory=torch.cuda.is_available(),
    )


def get_inferer(patch_size):
    """returns a sliding window inference instance."""

    sw_batch_size, overlap = 2, 0.5
    inferer = monai.inferers.SlidingWindowInferer(
        roi_size=patch_size,
        sw_batch_size=sw_batch_size,
        overlap=overlap,
        mode="gaussian",
        padding_mode="replicate",
    )
    return inferer
