#!/usr/bin/env python3
"""CPU oracle for the lab's own 2x2 RGBA32F linear/clamp sampling probe.

Normalized coordinates, level zero, texel centers at (index + .5) / size.
This is not an FSR reference implementation.
"""
import math


TEXELS = (
    (1.0, 2.0, 3.0, 4.0), (5.0, 6.0, 7.0, 8.0),
    (9.0, 10.0, 11.0, 12.0), (13.0, 14.0, 15.0, 16.0),
)
U = (.25, .75, .25, .75, .5, 0., 1., -.25,
     1.25, .25, .75, .5, .125, .875, .5, .5)
V = (.25, .25, .75, .75, .5, 0., 1., .5,
     .5, .5, .5, .25, .125, .875, -.25, 1.25)


def sample_linear_clamp(texels, width, height, u, v):
    """Return one RGBA sample, clamping each contributing texel to the edge."""
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError('Image dimensions must be positive integers')
    if len(texels) != width * height or any(len(pixel) != 4 for pixel in texels):
        raise ValueError('Expected width*height RGBA texels in row-major order')
    if not all(math.isfinite(x) for pixel in texels for x in pixel):
        raise ValueError('Texels must be finite')
    if not math.isfinite(u) or not math.isfinite(v):
        raise ValueError('Coordinates must be finite')
    x, y = u * width - .5, v * height - .5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0

    def pixel(ix, iy):
        return texels[min(height - 1, max(0, iy)) * width + min(width - 1, max(0, ix))]

    p00, p10 = pixel(x0, y0), pixel(x0 + 1, y0)
    p01, p11 = pixel(x0, y0 + 1), pixel(x0 + 1, y0 + 1)
    return tuple((1 - fy) * ((1 - fx) * p00[c] + fx * p10[c])
                 + fy * ((1 - fx) * p01[c] + fx * p11[c]) for c in range(4))


def contract():
    samples = [sample_linear_clamp(TEXELS, 2, 2, u, v) for u, v in zip(U, V)]
    return {
        'schema_version': 1, 'kind': 'synthetic-image-sampler-not-fsr',
        'width': 2, 'height': 2, 'format': 'VK_FORMAT_R32G32B32A32_SFLOAT',
        'texels_row_major_rgba': [list(p) for p in TEXELS],
        'u': list(U), 'v': list(V), 'normalized_coordinates': True,
        'filter': 'linear', 'address_mode': 'clamp-to-edge', 'mip_level': 0,
        'output_layout': 'channel-major-4x16-float32',
        'expected': [samples[lane][c] for c in range(4) for lane in range(16)],
        'absolute_tolerance': 1e-5, 'relative_tolerance': 0.,
        'image_heap_slot': 3, 'output_heap_slot': 7,
        'heap_set': 0, 'heap_binding': 0, 'descriptor_count': 16,
        'push_size': 52, 'table_pc_base': 4, 'placeholder_workgroup': [2, 1, 5],
        'cm_local_size': [1, 1, 1], 'gpu_validated': False,
    }
