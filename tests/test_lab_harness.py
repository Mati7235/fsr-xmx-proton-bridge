"""CPU reference-model and static safety checks; never execute the C harness."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "lab/bridge_probe.c").read_text()
RESOURCE_SLOTS = (7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10)
WORD_COUNT = 128
BUFFER_COUNT = 16
SENTINEL = 0xA5C39E71
CANARY_MAGIC = 0x584D5843


def validate_canary(buffers):
    if len(buffers) != BUFFER_COUNT or buffers[0][0] != CANARY_MAGIC:
        raise ValueError("bad canary marker")
    if any(word != SENTINEL for slot, words in enumerate(buffers)
           for index, word in enumerate(words) if (slot, index) != (0, 0)):
        raise ValueError("canary changed another word")


def validate_probe(buffers):
    if len(buffers) != BUFFER_COUNT or any(len(words) != WORD_COUNT for words in buffers):
        raise ValueError("wrong buffer shape")
    for argument, slot in enumerate(RESOURCE_SLOTS):
        if buffers[slot] != [16.0 + argument] * WORD_COUNT:
            raise ValueError(f"wrong output at heap slot {slot}")
    if any(word != SENTINEL for words in buffers[11:]
           for word in words):
        raise ValueError("untouched heap slots changed")


class LabHarnessContractTests(unittest.TestCase):
    def test_gpu_path_requires_explicit_opt_in(self):
        main = SOURCE[SOURCE.index("main(int argc") :]
        self.assertIn('strcmp(argv[i], "--run-gpu") == 0', main)
        self.assertIn('if (!run) {', main)
        self.assertLess(main.index('if (!run) {'), main.index("run_gpu(probe_dir, log_dir, icd_manifest, icd_root)"))

    def test_target_and_shader_selection_are_pinned(self):
        self.assertIn("#define VENDOR_INTEL 0x8086u", SOURCE)
        self.assertIn("#define DEVICE_BMG_G21 0xe20bu", SOURCE)
        self.assertIn('"%s/wg1_1_5.cmk"', SOURCE)
        self.assertIn('"%s/placeholder.spv"', SOURCE)
        self.assertIn('"%s/canary.spv"', SOURCE)
        self.assertIn('"--icd-manifest"', SOURCE)
        self.assertIn('"--icd-root"', SOURCE)

    def test_resource_map_and_readback_are_deterministic(self):
        self.assertIn("{7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10}", SOURCE)
        self.assertIn("#define WORDS_PER_BUFFER 128u", SOURCE)
        self.assertIn("#define PUSH_BYTES 52u", SOURCE)
        self.assertIn("push[0] = ROOT_CONSTANT", SOURCE)
        self.assertIn("push[12] = 0xd00df00du", SOURCE)
        self.assertIn("actual != expected", SOURCE)
        self.assertIn("is_sentinel(b)", SOURCE)

    def test_canary_and_injection_evidence_are_required(self):
        self.assertIn("/anv_canary", SOURCE)
        self.assertIn('"patched ANV"', SOURCE)
        self.assertIn('"injected"', SOURCE)
        self.assertIn('"dispatch kernel 1,1,5"', SOURCE)
        self.assertIn("/canary-driver.log", SOURCE)
        self.assertIn("/probe-driver.log", SOURCE)
        self.assertIn("direct_heap_layout_in_log(probe_log)", SOURCE)
        self.assertIn("clear_inherited_prefix(\"ANV_CM_\")", SOURCE)

    def test_queue_wait_is_fenced_and_bounded(self):
        self.assertIn("vkWaitForFences", SOURCE)
        self.assertIn("QUEUE_WAIT_TIMEOUT_NS 20000000000ull", SOURCE)
        self.assertNotIn("vkQueueWaitIdle", SOURCE)
        self.assertNotRegex(SOURCE, r"vkDeviceWaitIdle\s*\(")

    def test_dispatch_log_capture_includes_command_recording(self):
        submit = SOURCE[SOURCE.index("submit_once(VkPipeline"):SOURCE.index("fill_sentinels(void)")]
        self.assertLess(submit.index("redirect_stderr(log_path)"), submit.index("vkCmdDispatch(cmd"))
        self.assertGreater(submit.index("restore_stderr(saved)"), submit.index("vkWaitForFences("))

    def test_cpu_reference_model_accepts_only_expected_readback(self):
        canary = [[SENTINEL] * WORD_COUNT for _ in range(BUFFER_COUNT)]
        canary[0][0] = CANARY_MAGIC
        validate_canary(canary)
        probe = [[SENTINEL] * WORD_COUNT for _ in range(BUFFER_COUNT)]
        for arg, slot in enumerate(RESOURCE_SLOTS):
            probe[slot] = [16.0 + arg] * WORD_COUNT
        validate_probe(probe)
        probe[7][0] = -1.0
        with self.assertRaises(ValueError):
            validate_probe(probe)


if __name__ == "__main__":
    unittest.main()
