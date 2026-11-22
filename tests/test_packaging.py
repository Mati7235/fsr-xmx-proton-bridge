#!/usr/bin/env python3
"""Tests for the game/ and driver/ wrappers, all in temporary folders."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GAME_INSTALL = REPO / "game" / "install.sh"
GAME_UNINSTALL = REPO / "game" / "uninstall.sh"
DRIVER_INSTALL = REPO / "driver" / "install.sh"
DRIVER_UNINSTALL = REPO / "driver" / "uninstall.sh"
BUILD_RELEASE = REPO / "tools" / "build_release.py"
CLI = REPO / "installer" / "fsr-xmx"
REAL_PROFILE = REPO / "installer" / "profiles" / "cyberpunk2077.conf"

SCRIPTS = (GAME_INSTALL, GAME_UNINSTALL, DRIVER_INSTALL, DRIVER_UNINSTALL)
DOCS = (
    REPO / "game" / "README.md",
    REPO / "driver" / "README.md",
    REPO / "game" / "PUT-THE-FILES-HERE.txt",
    REPO / "README.md",
)

INI_ORIGINAL = (
    b"; test ini\r\n"
    b"\r\n"
    b"[Upscalers]\r\n"
    b"\r\n"
    b"Dx12Upscaler = auto\r\n"
    b"\r\n"
    b"[FrameGen]\r\n"
    b"\r\n"
    b"Enabled = false\r\n"
    b"\r\n"
    b"FGInput = Upscaler\r\n"
    b"\r\n"
    b"FGOutput = auto\r\n"
    b"\r\n"
    b"FGNvngxReplacement = auto\r\n"
    b"\r\n"
    b"DisableHudless = auto\r\n"
    b"\r\n"
    b"[Spoofing]\r\n"
    b"\r\n"
    b"SpoofedVendorId = auto\r\n"
    b"\r\n"
    b"SpoofedDeviceId = 0x2684\r\n"
    b"\r\n"
    b"Dxgi = true\r\n"
    b"\r\n"
    b"[FSR]\r\n"
    b"\r\n"
    b"Fsr4GpuSupport = auto\r\n"
    b"\r\n"
    b"Fsr4Preset = auto\r\n"
    b"\r\n"
    b"Fsr4Model = auto\r\n"
)


class PackagingTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp = Path(self.tmpdir.name)
        self.home = self.tmp / "home"
        self.steam = self.tmp / "steam"
        self.game = self.tmp / "game" / "bin" / "x64"
        self.profiles = self.tmp / "profiles"
        self.bundle = self.tmp / "bundle"
        self.sysfs = self.tmp / "sys"
        self.libvulkan = self.tmp / "lib" / "libvulkan.so.1"
        self.data_dir = self.home / "data"
        self.cache_dir = self.home / "cache"
        self.root = self.tmp / "driver-root"
        for path in (self.home, self.steam / "compatibilitytools.d",
                     self.sysfs / "bus" / "pci" / "drivers" / "xe",
                     self.libvulkan.parent, self.profiles, self.root,
                     self.tmp / "tmp"):
            path.mkdir(parents=True, exist_ok=True)
        self.libvulkan.write_bytes(b"loader\n")
        device = self.sysfs / "class" / "drm" / "card0" / "device"
        device.mkdir(parents=True)
        (device / "vendor").write_text("0x8086\n")
        (device / "device").write_text("0xe20b\n")
        (device / "driver").symlink_to(self.sysfs / "bus" / "pci" / "drivers" / "xe")
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(self.tmp / "tmp"),
            "XDG_DATA_HOME": str(self.data_dir),
            "XDG_CACHE_HOME": str(self.cache_dir),
            "FSR_XMX_PROFILES": str(self.profiles),
            "FSR_XMX_STEAM": str(self.steam),
            "FSR_XMX_SYSFS": str(self.sysfs),
            "FSR_XMX_VULKAN_LOADER": str(self.libvulkan),
        }
        self.make_game()
        self.make_bundle()
        self.make_profile()

    def run_script(self, script, *args, cwd=None, extra_env=None):
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        return subprocess.run([str(script), *args], env=env, text=True,
                              capture_output=True, cwd=str(cwd or self.tmp))

    def make_game(self):
        self.game.mkdir(parents=True)
        (self.game / "Cyberpunk2077.exe").write_bytes(b"MZ fake exe\n")
        (self.game / "amd_fidelityfx_upscaler_dx12.dll").write_bytes(b"mod xmx 4.1.2\n")
        (self.game / "fsr-original.dll").write_bytes(b"amd fsr 4.1.2\n")
        (self.game / "dxgi.dll").write_bytes(b"optiscaler proxy\n")
        (self.game / "OptiScaler.ini").write_bytes(INI_ORIGINAL)

    def make_bundle(self):
        files = {
            "MANIFEST": b"VERSION=test-1\nMESA=26.3.1\nVKD3D=2576c0b4\n",
            "icd/intel_icd.json": json.dumps({
                "file_format_version": "1.0.1",
                "ICD": {"api_version": "1.4.363", "library_path": "/nonexistent/driver.so"},
            }).encode() + b"\n",
            "lib/libvulkan_intel.so": b"fake anv\n",
            "igdext64.dll": b"igdext shim\n",
            "cabinet.dll": b"cabinet shim\n",
            "vkd3d-proton/x86_64-windows/d3d12.dll": b"vkd3d d3d12\n",
            "vkd3d-proton/x86_64-windows/d3d12core.dll": b"vkd3d d3d12core\n",
            "tools/cm-compile.sh": b"#!/bin/sh\nexit 0\n",
        }
        for name, data in files.items():
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        lines = ["%s  %s\n" % (self.sha(self.bundle / name), name)
                 for name in sorted(files)]
        (self.bundle / "SHA256SUMS").write_text("".join(lines))

    def make_profile(self):
        self.set_profile(
            MOD_SHA256=self.sha(self.game / "amd_fidelityfx_upscaler_dx12.dll"),
            MOD_SIZE=str((self.game / "amd_fidelityfx_upscaler_dx12.dll").stat().st_size),
            FSR_ORIGINAL_SHA256=self.sha(self.game / "fsr-original.dll"),
            FSR_ORIGINAL_SIZE=str((self.game / "fsr-original.dll").stat().st_size),
        )

    def set_profile(self, **values):
        out = []
        for line in REAL_PROFILE.read_text().splitlines(True):
            key = line.split("=", 1)[0]
            if key in values and "=" in line:
                out.append("%s=%s\n" % (key, values[key]))
            else:
                out.append(line)
        (self.profiles / "cyberpunk2077.conf").write_text("".join(out))

    @staticmethod
    def sha(path):
        import hashlib
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def tree(self, base):
        out = {}
        for path in sorted(Path(base).rglob("*")):
            rel = path.relative_to(base).as_posix()
            out[rel] = None if path.is_dir() else path.read_bytes()
        return out

    def install_release(self):
        result = subprocess.run([str(CLI), "install", "--from", str(self.bundle)],
                                env=dict(self.env), text=True, capture_output=True,
                                cwd=str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def driver_folder(self, with_bundle=True):
        folder = self.tmp / "driver"
        if not folder.exists():
            folder.mkdir()
            for name in ("install.sh", "uninstall.sh", "find-cli.sh"):
                shutil.copy2(REPO / "driver" / name, folder / name)
            shutil.copytree(REPO / "installer", folder / "fsr-xmx",
                            ignore=shutil.ignore_patterns("__pycache__"))
        if with_bundle and not (folder / "bundle").exists():
            shutil.copytree(self.bundle, folder / "bundle")
        return folder

    def build_release(self, root):
        result = subprocess.run(
            [sys.executable, "-I", str(BUILD_RELEASE), "--out", str(root)],
            env=dict(self.env), text=True, capture_output=True, cwd=str(self.tmp))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def released_game_folder(self):
        out = self.tmp / "release"
        self.build_release(out)
        released = self.tmp / "Cyberpunk 2077 x64"
        shutil.copytree(out / "fsr-xmx-game", released)
        for name in ("Cyberpunk2077.exe", "amd_fidelityfx_upscaler_dx12.dll",
                     "fsr-original.dll", "dxgi.dll", "OptiScaler.ini"):
            (released / name).write_bytes((self.game / name).read_bytes())
        self.assertFalse((released.parent / "installer").exists())
        return released

    def backups(self):
        base = self.game / ".fsr-xmx-backup"
        if not base.is_dir():
            return []
        return sorted(path for path in base.iterdir() if path.is_dir())

    def test_scripts_are_valid_and_have_no_home_paths(self):
        for script in SCRIPTS:
            result = subprocess.run(["bash", "-n", str(script)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = script.read_text()
            self.assertTrue(text.startswith("#!/usr/bin/env bash"), script)
            self.assertNotIn("/home/", text, script)
        for doc in DOCS:
            self.assertTrue(doc.is_file(), doc)
            self.assertNotIn("/home/", doc.read_text(), doc)
        for readme, limit in ((REPO / "game" / "README.md", 39),
                              (REPO / "driver" / "README.md", 30)):
            lines = readme.read_text().splitlines()
            self.assertLessEqual(len(lines), limit, readme)

    def test_build_release_makes_a_self_contained_folder(self):
        out = self.tmp / "release"
        result = self.build_release(out)
        game = out / "fsr-xmx-game"
        self.assertIn(str(game), result.stdout)
        for rel in ("install.sh", "uninstall.sh", "find-cli.sh", "README.md",
                    "PUT-THE-FILES-HERE.txt", "fsr-xmx/fsr-xmx",
                    "fsr-xmx/lib/common.sh", "fsr-xmx/lib/ini_edit.py",
                    "fsr-xmx/lib/vdf.py",
                    "fsr-xmx/profiles/cyberpunk2077.conf"):
            self.assertTrue((game / rel).is_file(), rel)
        self.assertTrue(os.access(game / "install.sh", os.X_OK))
        self.assertTrue(os.access(game / "uninstall.sh", os.X_OK))
        self.assertTrue(os.access(game / "fsr-xmx/fsr-xmx", os.X_OK))
        self.assertFalse((game / "installer").exists())
        self.assertEqual(list(game.rglob("*.dll")), [])
        self.assertEqual(list(game.rglob("*.ini")), [])
        self.assertEqual([path.name for path in (game / "fsr-xmx/profiles").iterdir()],
                         ["cyberpunk2077.conf"])

        driver = out / "fsr-xmx-driver"
        for rel in ("install.sh", "uninstall.sh", "find-cli.sh",
                    "fsr-xmx/fsr-xmx", "fsr-xmx/lib/common.sh",
                    "fsr-xmx/profiles/cyberpunk2077.conf"):
            self.assertTrue((driver / rel).is_file(), rel)
        self.assertEqual(list(driver.rglob("*.dll")), [])

        before = self.tree(out)
        stale = game / "stale.txt"
        stale.write_text("from an older build\n")
        self.build_release(out)
        self.assertFalse(stale.exists())
        self.assertEqual(self.tree(out), before)

    def test_released_game_folder_installs_without_the_repository(self):
        self.install_release()
        released = self.released_game_folder()
        tool = released / "fsr-xmx" / "fsr-xmx"
        before = self.tree(released)

        result = self.run_script(released / "install.sh", cwd=released)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"%s" run --profile cyberpunk2077 -- %%command%%' % tool,
                      result.stdout)
        self.assertNotIn("<path-to-fsr-xmx>", result.stdout)
        self.assertNotIn(str(REPO), result.stdout)
        self.assertTrue((released / ".fsr-xmx-backup").is_dir())
        self.assertIn(b"Dx12Upscaler = ffx", (released / "OptiScaler.ini").read_bytes())

        result = self.run_script(released / "uninstall.sh", cwd=released)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.tree(released)
        for rel in list(after):
            if rel.startswith(".fsr-xmx-backup"):
                del after[rel]
        self.assertEqual(after, before)

    def test_released_driver_folder_finds_its_own_tool(self):
        out = self.tmp / "release"
        self.build_release(out)
        released = self.tmp / "driver folder"
        shutil.copytree(out / "fsr-xmx-driver", released)
        shutil.copytree(self.bundle, released / "bundle")
        self.assertFalse((released.parent / "installer").exists())
        result = self.run_script(released / "install.sh",
                                 "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "opt/fsr-xmx/igdext64.dll").is_file())
        self.assertNotIn(str(REPO), result.stdout)

    def test_scripts_explain_an_incomplete_download(self):
        lonely = self.tmp / "lonely"
        lonely.mkdir()
        for name in ("install.sh", "uninstall.sh", "find-cli.sh"):
            shutil.copy2(REPO / "game" / name, lonely / name)
        for name in ("install.sh", "uninstall.sh"):
            with self.subTest(script=name):
                result = self.run_script(lonely / name, str(self.game), cwd=lonely)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("This download is incomplete", result.stderr)
                self.assertIn("fsr-xmx/", result.stderr)

    def test_game_install_requires_the_exe(self):
        before = self.tree(self.game)
        (self.game / "Cyberpunk2077.exe").rename(self.game / "moved.exe")
        result = self.run_script(GAME_INSTALL, str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cyberpunk2077.exe is not in", result.stderr)
        self.assertIn("bin/x64", result.stderr)
        self.assertEqual(self.backups(), [])
        (self.game / "moved.exe").rename(self.game / "Cyberpunk2077.exe")
        self.assertEqual(self.tree(self.game), before)

    def test_game_install_requires_each_payload_file(self):
        for name in ("amd_fidelityfx_upscaler_dx12.dll", "fsr-original.dll",
                     "dxgi.dll", "OptiScaler.ini"):
            with self.subTest(name=name):
                before = self.tree(self.game)
                held = self.tmp / ("held-" + name)
                (self.game / name).rename(held)
                result = self.run_script(GAME_INSTALL, str(self.game))
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(name, result.stderr)
                self.assertIn("PUT-THE-FILES-HERE.txt", result.stderr)
                self.assertEqual(self.backups(), [])
                self.assertFalse((self.game / ".fsr-xmx-backup").exists())
                held.rename(self.game / name)
                self.assertEqual(self.tree(self.game), before)

    def test_game_install_explains_the_optiscaler_rename(self):
        before = self.tree(self.game)
        (self.game / "dxgi.dll").rename(self.game / "OptiScaler.dll")
        result = self.run_script(GAME_INSTALL, str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OptiScaler.dll is", result.stderr)
        self.assertIn("rename it", result.stderr)
        self.assertIn("dxgi.dll", result.stderr)
        self.assertEqual(self.backups(), [])
        (self.game / "OptiScaler.dll").rename(self.game / "dxgi.dll")
        self.assertEqual(self.tree(self.game), before)

    def test_docs_explain_the_optiscaler_rename(self):
        for doc in (REPO / "game" / "PUT-THE-FILES-HERE.txt",
                    REPO / "game" / "README.md", REPO / "README.md"):
            text = doc.read_text(encoding="utf-8")
            self.assertIn("OptiScaler.dll", text, doc)
            self.assertIn("dxgi.dll", text, doc)
            self.assertIn("rename", text, doc)
        self.assertIn("mv OptiScaler.dll dxgi.dll",
                      (REPO / "game" / "PUT-THE-FILES-HERE.txt").read_text())

    def test_driver_install_names_the_game_download(self):
        result = self.run_script(self.driver_folder() / "install.sh",
                                 "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fsr-xmx-game", result.stdout)
        self.assertNotIn("game/README.md", result.stdout)

    def test_game_install_rejects_a_wrong_mod(self):
        before = self.tree(self.game)
        (self.game / "amd_fidelityfx_upscaler_dx12.dll").write_bytes(b"other mod\n")
        result = self.run_script(GAME_INSTALL, str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nitec's FSR4 XMX 4.1.2 mod", result.stderr)
        self.assertIn("PUT-THE-FILES-HERE.txt", result.stderr)
        self.assertEqual(self.backups(), [])
        (self.game / "amd_fidelityfx_upscaler_dx12.dll").write_bytes(
            before["amd_fidelityfx_upscaler_dx12.dll"])
        self.assertEqual(self.tree(self.game), before)

    def test_game_install_requires_the_driver_step(self):
        before = self.tree(self.game)
        result = self.run_script(GAME_INSTALL, str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("driver step has not run", result.stderr)
        self.assertIn("driver/install.sh", result.stderr)
        self.assertEqual(self.backups(), [])
        self.assertEqual(self.tree(self.game), before)

    def test_game_install_and_uninstall_round_trip(self):
        self.install_release()
        before = self.tree(self.game)
        result = self.run_script(GAME_INSTALL, str(self.game))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("%s run --profile cyberpunk2077 -- %%command%%" % CLI,
                      result.stdout)
        self.assertIn("Launch Options", result.stdout)
        self.assertIn("./uninstall.sh", result.stdout)

        ini = (self.game / "OptiScaler.ini").read_bytes()
        self.assertNotEqual(ini, INI_ORIGINAL)
        self.assertIn(b"Dx12Upscaler = ffx", ini)
        self.assertIn(b"Fsr4Model = auto", ini)
        self.assertEqual((self.game / "igdext64.dll").read_bytes(), b"igdext shim\n")

        backups = self.backups()
        self.assertEqual(len(backups), 1)
        manifest = (backups[0] / "manifest.tsv").read_text()
        self.assertIn("replaced\tOptiScaler.ini\t", manifest)
        self.assertIn("added\tigdext64.dll", manifest)
        self.assertEqual((backups[0] / "files" / "OptiScaler.ini").read_bytes(),
                         INI_ORIGINAL)

        result = self.run_script(GAME_UNINSTALL, str(self.game))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.tree(self.game)
        for rel in list(after):
            if rel.startswith(".fsr-xmx-backup"):
                del after[rel]
        self.assertEqual(after, before)
        self.assertIn("Remove the fsr-xmx line", result.stdout)

    def test_game_uninstall_without_install_fails(self):
        result = self.run_script(GAME_UNINSTALL, str(self.game))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".fsr-xmx-backup is missing", result.stderr)

    def test_driver_test_root_needs_the_env_flag(self):
        result = self.run_script(self.driver_folder() / "install.sh",
                                 "--test-root", str(self.root))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FSR_XMX_DRIVER_TEST_ROOT=1", result.stderr)
        self.assertEqual(self.tree(self.root), {})

    def test_driver_install_rejects_a_missing_bundle(self):
        folder = self.driver_folder(with_bundle=False)
        result = self.run_script(folder / "install.sh",
                                 "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("This download is incomplete", result.stderr)
        self.assertIn("bundle folder is missing", result.stderr)
        self.assertEqual(result.stderr.strip().count("."), 1)
        self.assertEqual(self.tree(self.root), {})

    def test_driver_install_rejects_the_old_from_option(self):
        result = self.run_script(self.driver_folder() / "install.sh",
                                 "--from", str(self.bundle),
                                 "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown option: --from", result.stderr)
        self.assertEqual(self.tree(self.root), {})

    def test_driver_install_writes_into_a_test_root(self):
        result = self.run_script(self.driver_folder() / "install.sh",
                                 "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        lib = self.root / "usr/lib/fsr-xmx/libvulkan_intel.so"
        icd = self.root / "usr/share/vulkan/icd.d/fsr-xmx-intel_icd.json"
        env_file = self.root / "etc/environment.d/fsr-xmx.conf"
        self.assertEqual(lib.read_bytes(), (self.bundle / "lib/libvulkan_intel.so").read_bytes())
        data = json.loads(icd.read_text())
        self.assertEqual(data["ICD"]["library_path"], str(lib))
        self.assertEqual((self.root / "opt/fsr-xmx/igdext64.dll").read_bytes(),
                         b"igdext shim\n")
        self.assertEqual((self.root / "opt/fsr-xmx/cabinet.dll").read_bytes(),
                         b"cabinet shim\n")

        text = env_file.read_text()
        self.assertIn("VK_DRIVER_FILES=%s\n" % icd, text)
        self.assertIn("ANV_CM_KERNEL_DIR=${HOME}/.cache/fsr-xmx/kernels", text)
        self.assertIn("WINEDLLOVERRIDES=dxgi,cabinet=n,b", text)
        self.assertNotIn("FSR4_XMX", text)
        self.assertTrue((self.root / "opt/fsr-xmx/created.tsv").is_file())
        self.assertTrue((self.data_dir / "fsr-xmx" / "versions" / "test-1").is_dir())
        self.assertIn("log out and back in", result.stdout)
        self.assertIn("export VK_DRIVER_FILES=%s" % icd, result.stdout)

    def test_driver_uninstall_refuses_a_modified_file(self):
        folder = self.driver_folder()
        self.run_script(folder / "install.sh",
                        "--test-root", str(self.root),
                        extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        icd = self.root / "usr/share/vulkan/icd.d/fsr-xmx-intel_icd.json"
        with open(icd, "a", encoding="utf-8") as handle:
            handle.write("edited\n")
        result = self.run_script(folder / "uninstall.sh", "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(icd), result.stderr)
        self.assertIn("changed since the install", result.stderr)
        self.assertTrue(icd.is_file())
        self.assertTrue((self.root / "opt/fsr-xmx/created.tsv").is_file())

    def test_driver_uninstall_keeps_foreign_files(self):
        icd_dir = self.root / "usr/share/vulkan/icd.d"
        icd_dir.mkdir(parents=True)
        foreign = icd_dir / "intel_icd.x86_64.json"
        foreign.write_text('{"ICD": {}}\n')
        folder = self.driver_folder()
        self.run_script(folder / "install.sh",
                        "--test-root", str(self.root),
                        extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        result = self.run_script(folder / "uninstall.sh", "--test-root", str(self.root),
                                 extra_env={"FSR_XMX_DRIVER_TEST_ROOT": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(foreign.read_text(), '{"ICD": {}}\n')
        self.assertFalse((self.root / "opt/fsr-xmx").exists())
        self.assertFalse((self.root / "etc/environment.d/fsr-xmx.conf").exists())
        self.assertFalse((self.root / "usr/lib/fsr-xmx").exists())
        self.assertFalse((icd_dir / "fsr-xmx-intel_icd.json").exists())
        self.assertTrue(icd_dir.is_dir())
        self.assertIn("Log out and back in", result.stdout)


if __name__ == "__main__":
    unittest.main()
