"""Pins del inventario estatico XMX 4.1.2. Solo estatico, sin GPU/Wine/ejecucion.

Fail-closed: cualquier deriva de hash, tamano, export, import o recurso
falla en lugar de pasar en silencio. Los casos con artefacto propietario
se omiten si la DLL o el JSON local no estan presentes.
"""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll"
JSON = ROOT / "analysis/xmx412-static.json"

EXPECTED_SHA = "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732"
EXPECTED_SIZE = 45558272

EXPECTED_EXPORTS = [
    ("OptiPluginInit", 1, 0x6FC20),
    ("ffxConfigure", 2, 0x1FC0),
    ("ffxCreateContext", 3, 0x2020),
    ("ffxDestroyContext", 4, 0x20D0),
    ("ffxDispatch", 5, 0x2140),
    ("ffxQuery", 6, 0x21A0),
]

EXPECTED_RESOURCES = {
    (10, 40101): (6107632, "8e260219b64694f1d5aa6020632b0d107abff759f200a728b788aed454e9b9b5"),
    (10, 40102): (3856836, "58557640463eeec42c0b9ea923d6b7462af2c38e97976be55c9e3501134d7651"),
    (10, 40103): (6960934, "48963849d7b456256fb4e238353be436d6bb17b8385e8cb7857bb901f929f458"),
    (10, 40104): (8031050, "2c93c489f21415d4e8505b466669d529f1e397a4d0c9e6790acef326d9d25fa1"),
    (10, 40105): (3421152, "4cff7b12f864d69abf851ae8e88883475116fe80f1ad7841b955d6f9e90acb2f"),
    (10, 40106): (1001522, "579f610f8dba82752bdc130ed1de27b1abc4ff432f9963d419d038862d20b0de"),
    (16, 1): (776, "20ba4d46d50e77c3ade40c878900b68cf33a1cb98a26166364a1b2d5e78bd072"),
    (24, 2): (145, "d2952e57023848a37fb0f21f0dfb38c9000f610ac2b00c2f128511dfd68bde04"),
}

EXPECTED_402X = [
    "4.0.2X",
    "4.0.2X ASkip",
    "4.0.2X Hybrid",
    "4.0.2X Hybrid ASkip",
    "4.0.2X Hybrid QSkip",
    "4.0.2X Hybrid Skip",
    "4.0.2X QSkip",
    "4.0.2X Skip",
]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(JSON.exists(), "analysis/xmx412-static.json no presente")
class PinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(JSON.read_text(encoding="utf-8"))

    def test_artifact_pin(self):
        self.assertEqual(self.report["artifact"]["sha256"], EXPECTED_SHA)
        self.assertEqual(self.report["artifact"]["size_bytes"], EXPECTED_SIZE)
        self.assertEqual(self.report["artifact"]["arch"], "x86_64")
        self.assertEqual(self.report["artifact"]["bits"], 64)

    def test_exports_pin(self):
        exports = self.report["exports"]
        self.assertEqual(len(exports), 6)
        for (name, ordinal, rva), entry in zip(EXPECTED_EXPORTS, exports):
            self.assertEqual(entry["name"], name)
            self.assertEqual(entry["ordinal"], ordinal)
            self.assertEqual(entry["rva"], rva)
        self.assertFalse(self.report["answers"]["same_5_ffx_exports"])

    def test_imports_pin(self):
        imports = self.report["imports"]
        self.assertEqual(imports["dll_count"], 17)
        self.assertEqual(imports["function_count"], 181)
        self.assertEqual(imports["delay_imports"], 0)
        by_name = {d["name"]: d for d in imports["dlls"]}
        self.assertEqual(by_name["d3d12.dll"]["functions"], ["D3D12SerializeRootSignature"])
        self.assertEqual(by_name["dxgi.dll"]["functions"], ["CreateDXGIFactory2"])
        self.assertEqual(by_name["bcrypt.dll"]["functions"], ["BCryptHash"])
        self.assertEqual(sorted(by_name["Cabinet.dll"]["ordinals"]), [40, 43, 45])
        self.assertEqual(by_name["USER32.dll"]["functions"], ["MessageBoxA"])

    def test_resources_pin(self):
        resources = {
            (r["type"], r["name"]): (r["size_bytes"], r["sha256"])
            for r in self.report["resources"]
        }
        self.assertEqual(resources, EXPECTED_RESOURCES)

    def test_versioninfo_manifest_pin(self):
        versioninfo = self.report["versioninfo"]
        self.assertEqual(versioninfo["FileVersion"], "4.0.2.1")
        self.assertEqual(versioninfo["ProductVersion"], "4.0.2.1")
        self.assertEqual(versioninfo["size_bytes"], 776)
        self.assertEqual(
            versioninfo["raw_sha256"],
            "20ba4d46d50e77c3ade40c878900b68cf33a1cb98a26166364a1b2d5e78bd072",
        )
        manifest = self.report["manifest"]
        self.assertEqual(manifest["size_bytes"], 145)
        self.assertEqual(
            manifest["sha256"],
            "d2952e57023848a37fb0f21f0dfb38c9000f610ac2b00c2f128511dfd68bde04",
        )

    def test_model_strings_pin(self):
        models = self.report["model_strings"]
        self.assertEqual(models["model_4_0_2X"], EXPECTED_402X)
        self.assertIn("4.1.2X Lite", models["model_4_1_2X"])
        self.assertIn("FSR 4.1.2 Lite (DG2)", " ".join(models["lite_markers"]))
        self.assertTrue(models["has_opti_plugin_init"])
        self.assertFalse(models["has_create_device_extension_context2"])
        self.assertTrue(models["has_get_cached_blob"])
        self.assertEqual(models["context_requested"], "4.20.0")
        for n in range(1, 13):
            self.assertIn(n, models["passes_found"])
        self.assertIn("INTC_D3D12_CreateDeviceExtensionContext", self.report["intel_api_strings"])
        self.assertIn("INTC_D3D12_GetCachedBlob", self.report["intel_api_strings"])
        self.assertNotIn(
            "INTC_D3D12_CreateDeviceExtensionContext2",
            self.report["intel_api_strings"],
        )

    def test_rea_corrobortion_pin(self):
        rea = self.report["rea_corrobortion"]
        self.assertEqual(rea["exports"]["coverage"], "complete")
        self.assertEqual(rea["exports"]["exports"], 6)
        self.assertEqual(rea["imports"]["coverage"], "complete")
        self.assertEqual(rea["imports"]["examined_dlls"], 17)
        self.assertEqual(rea["imports"]["imports"], 181)
        self.assertEqual(rea["imports"]["delay_imports"], 0)
        self.assertEqual(rea["resources"]["coverage"], "complete")
        self.assertEqual(rea["resources"]["resources"], 8)


@unittest.skipUnless(DLL.exists() and JSON.exists(), "DLL o JSON local no presente")
class DllMatchTests(unittest.TestCase):
    def test_dll_bytes_match_json(self):
        data = DLL.read_bytes()
        report = json.loads(JSON.read_text(encoding="utf-8"))
        self.assertEqual(len(data), EXPECTED_SIZE)
        self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED_SHA)
        self.assertEqual(len(data), report["artifact"]["size_bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), report["artifact"]["sha256"])

    def test_tool_reproduces_json(self):
        tool = load("inspect_dll_412")
        fresh = tool.build_report(DLL)
        report = json.loads(JSON.read_text(encoding="utf-8"))
        self.assertEqual(fresh["artifact"], report["artifact"])
        self.assertEqual(fresh["exports"], report["exports"])
        self.assertEqual(fresh["resources"], report["resources"])
        self.assertEqual(fresh["versioninfo"], report["versioninfo"])
        self.assertEqual(fresh["manifest"], report["manifest"])
        self.assertEqual(fresh["intel_api_strings"], report["intel_api_strings"])
        self.assertEqual(fresh["evidence_strings"], report["evidence_strings"])


class OldToolPreservedTests(unittest.TestCase):
    def test_inspect_dll_keys_unchanged(self):
        tool = load("inspect_dll")
        self.assertEqual(
            set(tool.inspect.__code__.co_names) & {"exports", "imports", "resources"},
            set(),
        )
        source = (ROOT / "tools/inspect_dll.py").read_text(encoding="utf-8")
        self.assertIn("intel_api_strings", source)
        # La salida vieja solo tiene estas 6 claves; el inventario nuevo vive en otro modulo.
        if DLL.exists():
            result = tool.inspect(DLL)
            self.assertEqual(
                sorted(result.keys()),
                ["evidence_strings", "intel_api_strings", "limitations", "path", "sha256", "size_bytes"],
            )


if __name__ == "__main__":
    unittest.main()
