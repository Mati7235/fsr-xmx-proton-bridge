"""CPU-only contract and raw-readback model; never execute image_probe/Vulkan."""
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'lab/image_probe.c').read_text()
sys.path.insert(0, str(ROOT / 'tools'))
from image_probe_reference import contract


def c_float_array(name):
    match = re.search(rf'static const float {name}\[[^]]+\] = \{{(.*?)\}};',
                      SOURCE, re.S)
    if not match:
        raise AssertionError(f'missing C array {name}')
    return [float(value) for value in re.findall(
        r'(?<![A-Za-z0-9_])(-?(?:\d+(?:\.\d*)?|\.\d+))f', match.group(1))]


def validate_raw(raw):
    spec = contract()
    if len(raw) != 16 * 128 * 4:
        raise ValueError('raw dump must contain sixteen 128-word slots')
    words = struct.unpack('<2048I', raw)
    sentinel = 0xA5C39E71
    output_slot = spec['output_heap_slot']
    for slot in range(16):
        for word in range(128):
            actual = words[slot * 128 + word]
            if slot == output_slot and word < 64:
                expected = struct.unpack('<I', struct.pack('<f', spec['expected'][word]))[0]
                actual_float = struct.unpack('<f', struct.pack('<I', actual))[0]
                if abs(actual_float - spec['expected'][word]) > spec['absolute_tolerance']:
                    raise ValueError('output does not match independent oracle')
                if actual != expected:
                    raise ValueError('fixture output changed unexpectedly')
            elif actual != sentinel:
                raise ValueError(f'non-output word changed at slot {slot}, word {word}')


class ImageHarnessContractTests(unittest.TestCase):
    def test_frozen_vectors_match_shared_oracle_exactly(self):
        spec = contract()
        texels = [x for pixel in spec['texels_row_major_rgba'] for x in pixel]
        self.assertEqual(c_float_array('image_texels'), texels)
        self.assertEqual(c_float_array('sample_u'), spec['u'])
        self.assertEqual(c_float_array('sample_v'), spec['v'])
        self.assertEqual(c_float_array('expected'), spec['expected'])

    def test_resource_and_execution_contract_is_pinned(self):
        spec = contract()
        self.assertEqual(spec['image_heap_slot'], 3)
        self.assertEqual(spec['output_heap_slot'], 7)
        self.assertEqual(spec['push_size'], 52)
        self.assertEqual(spec['table_pc_base'], 4)
        self.assertEqual(spec['placeholder_workgroup'], [2, 1, 5])
        self.assertEqual(spec['output_layout'], 'channel-major-4x16-float32')
        for token in ('#define IMAGE_SLOT 3u', '#define OUTPUT_SLOT 7u',
                      '#define PUSH_BYTES 52u', '#define ABS_TOLERANCE 1.0e-5f',
                      'push[1] = IMAGE_SLOT', 'push[2] = OUTPUT_SLOT',
                      'push[12] = 0'):
            self.assertIn(token, SOURCE)

    def test_gpu_execution_is_explicit_and_paths_match_launcher_contract(self):
        self.assertIn('strcmp(argv[i], "--run-gpu") == 0', SOURCE)
        self.assertIn('if (!run)', SOURCE)
        self.assertIn('"%s/wg2_1_5.cmk"', SOURCE)
        self.assertIn('"--probe-dir"', SOURCE)
        self.assertIn('"--log-dir"', SOURCE)
        self.assertIn('"--icd-manifest"', SOURCE)
        self.assertIn('"--icd-root"', SOURCE)
        self.assertIn('mkdir(log_dir, 0700)', SOURCE)

    def test_mutable_heap_and_immutable_sampler_are_explicit(self):
        for token in ('VK_EXT_MUTABLE_DESCRIPTOR_TYPE_EXTENSION_NAME',
                      'mutable_features.mutableDescriptorType',
                      'VK_DESCRIPTOR_TYPE_MUTABLE_EXT',
                      'VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE',
                      'i == IMAGE_SLOT ? VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE',
                      '.pImmutableSamplers = &sampler',
                      '.minFilter = VK_FILTER_LINEAR', '.magFilter = VK_FILTER_LINEAR',
                      'VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE',
                      'VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT'):
            self.assertIn(token, SOURCE)

    def test_canary_injection_dispatch_and_readback_gates(self):
        self.assertIn('file_contains(probe_log, "injected")', SOURCE)
        self.assertIn('direct_heap_layout_in_log(probe_log)', SOURCE)
        self.assertIn('dispatch kernel 2,1,5', SOURCE)
        self.assertIn('image-readback.bin', SOURCE)
        self.assertIn('fwrite(mapped[slot], sizeof(uint32_t), WORDS_PER_BUFFER, file)', SOURCE)
        self.assertIn('QUEUE_WAIT_TIMEOUT_NS 20000000000ull', SOURCE)
        self.assertNotIn('vkQueueWaitIdle', SOURCE)
        self.assertNotRegex(SOURCE, r'vkDeviceWaitIdle\s*\(')

    def test_raw_readback_model_accepts_only_output_and_rejects_corruption(self):
        words = [0xA5C39E71] * (16 * 128)
        for i, value in enumerate(contract()['expected']):
            words[7 * 128 + i] = struct.unpack('<I', struct.pack('<f', value))[0]
        raw = struct.pack('<2048I', *words)
        validate_raw(raw)
        corrupted = bytearray(raw)
        corrupted[(7 * 128 + 64) * 4] ^= 1
        with self.assertRaises(ValueError):
            validate_raw(corrupted)
        corrupted = bytearray(raw)
        corrupted[(3 * 128) * 4] ^= 1
        with self.assertRaises(ValueError):
            validate_raw(corrupted)


if __name__ == '__main__':
    unittest.main()
