import numpy as np


def biased_round(value):
    """Bias ties away from the cusp to prevent rounding oscillation."""
    bias = 1e-10 if value > 0 else -1e-10
    return round(value + bias)


def interpolate_to_length(input_array, n):
    """Interpolates an input numpy array to a new array of length n."""
    new_array = np.zeros(n)

    original_indices = np.linspace(0, n - 1, num=len(input_array), dtype=int)

    new_array[original_indices] = input_array

    for i in range(1, len(original_indices)):
        start_idx, end_idx = original_indices[i - 1], original_indices[i]
        new_array[start_idx : end_idx + 1] = np.linspace(
            input_array[i - 1], input_array[i], end_idx - start_idx + 1
        )

    return new_array


def tween(a, b, t):
    """Tweens between two values a and b by a factor t."""
    return a + (b - a) * t


class Pose:
    def __init__(self, x, y, ang, size, life, alpha=1.0):
        """Initialize a new pose object."""
        self.x = x
        self.y = y
        self.ang = ang
        self.size = size
        self.life = life
        self.alpha = alpha

        self.d_pos = (0, 0)
        self.d_rotation = 0
        self.d_size = 0
        self.d_alpha = 0

        self.modifier_callbacks = []

    def set_vectors(self, x, y, ang, size, life, alpha=1.0):
        """Set the vector values of the pose."""
        self.x = x
        self.y = y
        self.ang = ang
        self.size = size
        self.life = life
        self.alpha = alpha

    def set_deltas(self, d_pos, d_rotation, d_size):
        """Set position, rotation and size changes per second."""
        self.d_pos = d_pos
        self.d_rotation = d_rotation
        self.d_size = d_size

    def apply_d_pos(self, dt):
        """Apply position change over dt seconds."""
        lin, ang = self.d_pos
        ang_radians = ang * -2 * np.pi
        direction = np.array([np.cos(ang_radians), np.sin(ang_radians)])
        movement_vector = direction * lin * dt
        self.x += movement_vector[0]
        self.y += movement_vector[1]

    def update(self, dt):
        """Advance pose and lifetime by dt seconds."""
        self.life -= dt
        if self.life <= 0.0:
            return False

        self.ang = (((self.ang + 1) + self.d_rotation * dt) % 2) - 1
        self.apply_d_pos(dt)

        self.alpha += self.d_alpha * dt
        self.size += self.d_size * dt

        for modifier in self.modifier_callbacks:
            modifier(self, dt)

        return True
