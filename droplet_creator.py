import os

import numpy as np

# duration of droplet animation
N_FRAMES = 60
# size of animation on strip (will probably be scaled anyway)
WIDTH = 60
# name this droplet animation
NAME = "my_cool_droplet"


def droplet_maths(x: np.ndarray, frame_counter: int) -> np.ndarray:
    return np.sin(x + frame_counter)


# No touching below here
radius = WIDTH // 2
_, droplet = np.mgrid[:N_FRAMES, -radius:radius]

for frame_counter, x in enumerate(droplet):
    frame = droplet_maths(x, frame_counter)
    # clip the values to between 0 and 1
    frame[frame < 0] = 0
    frame[frame > 1] = 1
    droplet[frame_counter, :] = frame

# automatically generate filename and save
dir_path = os.path.dirname(os.path.realpath(__file__))
droplets_location = os.path.join(dir_path, "ledfx", "effects", "droplets")
assert os.path.isdir(droplets_location)

path = os.path.join(droplets_location, f"{NAME}.npy")
i = 0
while os.path.exists(path):
    i += 1
    path = os.path.join(droplets_location, f"{NAME}_{i}.npy")

np.save(path, droplet)
print(f"Done! Saved as {NAME}_{i}.npy - restart LedFx to see it in action.")
