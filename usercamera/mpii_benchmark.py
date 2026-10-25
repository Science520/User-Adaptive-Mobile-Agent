"""CPU encoder timing, explicitly excluding acquisition/detection/crop preparation."""
import time
from pathlib import Path
import numpy as np


def benchmark_encoder(root):
    import torch
    from torchvision.models import resnet18
    from .mpii_models import WEIGHTS_NAME
    torch.set_num_threads(4)
    base=resnet18(weights=None)
    base.load_state_dict(torch.load(Path(root)/'cache/torch/hub/checkpoints'/WEIGHTS_NAME,map_location='cpu',weights_only=True))
    base.fc=torch.nn.Identity();base.eval()
    timings={}
    with torch.inference_mode():
        for size in [64,224]:
            x=torch.zeros(3,3,size,size)
            for _ in range(3):base(x)
            elapsed=[]
            for _ in range(15):
                t=time.perf_counter();base(x);elapsed.append((time.perf_counter()-t)*1000)
            timings[str(size)]={'median_ms':float(np.median(elapsed)),'p90_ms':float(np.quantile(elapsed,.9)),
                                'three_crops_one_sample':True}
    return {'shared_encoder_parameters':sum(p.numel() for p in base.parameters()),'timings':timings,
            'device':'CPU, torch threads=4','scope':'three already resized/normalized face+eye tensors; excludes image decode, landmark detector, cropping, hardware IO and output projection; indicative desktop timing, not phone latency'}
